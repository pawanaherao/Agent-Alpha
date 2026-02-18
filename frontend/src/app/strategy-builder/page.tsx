"use client";

import React, { useState, useEffect, useRef } from 'react';
import { Send, Cpu, Code, Activity, Terminal } from 'lucide-react';

// === MOCK RULE ENGINE LOGIC (Client-Side for Demo) ===
// In production, this would call the Backend API with the LLM Prompt
const mockParseStrategy = (text: string) => {
    const config: any = {
        symbol: "NIFTY",
        entry_conditions: [],
        exit_conditions: []
    };

    const lower = text.toLowerCase();

    // 1. RSI Logic
    if (lower.includes("rsi")) {
        const valMatch = lower.match(/rsi.*?(?:below|less than).*?(\d+)/) || lower.match(/rsi.*?<.*?(\d+)/);
        if (valMatch) {
            config.entry_conditions.push({
                type: "RSI",
                period: 14,
                condition: "LT",
                value: parseInt(valMatch[1])
            });
        }
        const valMatchGt = lower.match(/rsi.*?(?:above|greater than).*?(\d+)/) || lower.match(/rsi.*?>.*?(\d+)/);
        if (valMatchGt) {
            config.entry_conditions.push({
                type: "RSI",
                period: 14,
                condition: "GT",
                value: parseInt(valMatchGt[1])
            });
        }
    }

    // 2. SMA/EMA Logic
    if (lower.includes("sma") || lower.includes("ema")) {
        const type = lower.includes("ema") ? "EMA" : "SMA";
        const periodMatch = lower.match(/(\d+)\s*(?:sma|ema)/);
        const period = periodMatch ? parseInt(periodMatch[1]) : 20;

        if (lower.includes("above") || lower.includes("gt")) {
            // Price > MA
            config.entry_conditions.push({
                type: type,
                period: period,
                condition: "LT", // MA < Price
                value: "CLOSE"
            });
        }
    }

    return config;
};

export default function StrategyBuilderPage() {
    const [messages, setMessages] = useState<{ role: 'user' | 'ai'; content: string }[]>([
        { role: 'ai', content: "Hello! I am Agent Alpha. Describe a strategy, and I will build it for you. (e.g., 'Buy NIFTY if RSI is below 30')" }
    ]);
    const [input, setInput] = useState("");
    const [isTyping, setIsTyping] = useState(false);
    const [strategyConfig, setStrategyConfig] = useState<any>(null);

    const messagesEndRef = useRef<HTMLDivElement>(null);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages]);

    const handleSend = async () => {
        if (!input.trim()) return;

        const userMsg = input;
        setMessages(prev => [...prev, { role: 'user', content: userMsg }]);
        setInput("");
        setIsTyping(true);

        // Simulate AI Delay
        setTimeout(() => {
            // 1. Generate Rules (Mock)
            const newConfig = mockParseStrategy(userMsg);
            setStrategyConfig(newConfig);

            // 2. Respond
            setMessages(prev => [...prev, {
                role: 'ai',
                content: `I've updated the strategy matrix based on your request:\n- Symbol: ${newConfig.symbol}\n- Added ${newConfig.entry_conditions.length} entry conditions.`
            }]);
            setIsTyping(false);
        }, 1500);
    };

    return (
        <div className="flex h-screen bg-neutral-900 text-gray-100 font-sans overflow-hidden">

            {/* LEFT: Chat Interface */}
            <div className="w-1/3 flex flex-col border-r border-neutral-800 bg-neutral-900">
                <div className="p-4 border-b border-neutral-800 flex items-center gap-2">
                    <Cpu className="w-5 h-5 text-blue-400" />
                    <h1 className="font-bold text-lg">Strategy Builder AI</h1>
                </div>

                {/* Messages */}
                <div className="flex-1 overflow-y-auto p-4 space-y-4">
                    {messages.map((m, i) => (
                        <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                            <div className={`max-w-[85%] rounded-lg p-3 text-sm leading-relaxed ${m.role === 'user'
                                    ? 'bg-blue-600 text-white'
                                    : 'bg-neutral-800 text-gray-300 border border-neutral-700'
                                }`}>
                                {m.content}
                            </div>
                        </div>
                    ))}
                    {isTyping && (
                        <div className="flex justify-start">
                            <div className="bg-neutral-800 text-gray-400 text-xs px-3 py-2 rounded-lg animate-pulse">
                                Thinking...
                            </div>
                        </div>
                    )}
                    <div ref={messagesEndRef} />
                </div>

                {/* Input */}
                <div className="p-4 bg-neutral-900 border-t border-neutral-800">
                    <div className="flex gap-2 relative">
                        <input
                            className="flex-1 bg-neutral-800 border border-neutral-700 rounded-md px-4 py-3 text-sm focus:outline-none focus:border-blue-500 transition-colors"
                            placeholder="Describe your strategy..."
                            value={input}
                            onChange={(e) => setInput(e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                        />
                        <button
                            onClick={handleSend}
                            className="absolute right-2 top-2 p-1.5 bg-blue-600 hover:bg-blue-500 rounded-md transition-colors"
                        >
                            <Send className="w-4 h-4 text-white" />
                        </button>
                    </div>
                </div>
            </div>

            {/* RIGHT: Visualizer */}
            <div className="flex-1 flex flex-col bg-neutral-950">
                <div className="p-4 border-b border-neutral-800 flex justify-between items-center bg-neutral-900">
                    <div className="flex items-center gap-2">
                        <Activity className="w-5 h-5 text-green-400" />
                        <h2 className="font-bold text-md">Universal Parameter Matrix (Live)</h2>
                    </div>
                    <div className="text-xs text-gray-500 flex items-center gap-1">
                        <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></div>
                        Engine Ready
                    </div>
                </div>

                <div className="flex-1 p-6 grid grid-rows-2 gap-6 overflow-hidden">

                    {/* Top: JSON Config Reader */}
                    <div className="bg-neutral-900 rounded-xl border border-neutral-800 p-4 flex flex-col shadow-xl">
                        <div className="flex items-center gap-2 mb-3 text-neutral-400 text-xs uppercase tracking-wider font-semibold">
                            <Code className="w-4 h-4" />
                            Generated Configuration
                        </div>
                        <div className="flex-1 bg-black rounded-lg p-4 overflow-auto border border-neutral-800 relative group">
                            <pre className="text-green-400 font-mono text-xs leading-5">
                                {strategyConfig
                                    ? JSON.stringify(strategyConfig, null, 2)
                                    : "// Waiting for AI generation..."}
                            </pre>
                        </div>
                    </div>

                    {/* Bottom: Strategy Visualization (Placeholder) */}
                    <div className="bg-neutral-900 rounded-xl border border-neutral-800 p-4 flex flex-col shadow-xl">
                        <div className="flex items-center gap-2 mb-3 text-neutral-400 text-xs uppercase tracking-wider font-semibold">
                            <Terminal className="w-4 h-4" />
                            Visual Logic Flow
                        </div>
                        <div className="flex-1 rounded-lg border border-neutral-800 border-dashed flex flex-col items-center justify-center text-neutral-600 gap-2">
                            {strategyConfig && strategyConfig.entry_conditions.length > 0 ? (
                                <div className="flex gap-4 items-center animate-in fade-in zoom-in duration-500">
                                    <div className="px-4 py-2 bg-neutral-800 rounded border border-neutral-700 text-gray-300">Start</div>
                                    <div className="h-px w-8 bg-neutral-700"></div>
                                    {strategyConfig.entry_conditions.map((c: any, i: number) => (
                                        <React.Fragment key={i}>
                                            <div className="px-4 py-2 bg-blue-900/30 border border-blue-500/50 rounded text-blue-200 text-sm">
                                                {c.type} {c.condition} {c.value}
                                            </div>
                                            <div className="h-px w-8 bg-neutral-700"></div>
                                        </React.Fragment>
                                    ))}
                                    <div className="px-4 py-2 bg-green-900/30 border border-green-500/50 rounded text-green-200 text-sm font-bold">BUY</div>
                                </div>
                            ) : (
                                <>
                                    <Activity className="w-8 h-8 opacity-20" />
                                    <span className="text-sm">Describe a strategy to visualize the flow</span>
                                </>
                            )}
                        </div>
                    </div>

                </div>
            </div>
        </div>
    );
}
