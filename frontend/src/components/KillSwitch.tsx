'use client';

import { useState } from 'react';
import { useDashboard } from '@/stores/dashboard';

export function KillSwitch() {
    const [isPressed, setIsPressed] = useState(false);
    const [showConfirm, setShowConfirm] = useState(false);
    const killSwitch = useDashboard(state => state.killSwitch);
    const positions = useDashboard(state => state.positions);

    const handleLongPress = () => {
        setIsPressed(true);
        setTimeout(() => {
            setShowConfirm(true);
        }, 2000);
    };

    const handleRelease = () => {
        setIsPressed(false);
        if (!showConfirm) {
            setShowConfirm(false);
        }
    };

    const handleConfirm = () => {
        killSwitch();
        setShowConfirm(false);
        setIsPressed(false);
    };

    return (
        <div className="relative">
            <button
                onMouseDown={handleLongPress}
                onMouseUp={handleRelease}
                onMouseLeave={handleRelease}
                onTouchStart={handleLongPress}
                onTouchEnd={handleRelease}
                className={`
          px-6 py-3 rounded-lg font-bold text-white transition-all
          ${isPressed
                        ? 'bg-red-700 scale-95 shadow-inner'
                        : 'bg-red-600 hover:bg-red-700 shadow-lg'
                    }
          ${positions.length === 0 ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
        `}
                disabled={positions.length === 0}
            >
                🛑 KILL SWITCH
            </button>

            {showConfirm && (
                <div className="absolute top-full mt-2 right-0 bg-zinc-900 border border-red-500 rounded-lg p-4 shadow-xl z-50 min-w-[300px]">
                    <p className="text-white font-semibold mb-2">⚠️ Confirm Kill Switch</p>
                    <p className="text-gray-400 text-sm mb-4">
                        This will close all {positions.length} positions and cancel all orders.
                    </p>
                    <div className="flex gap-2">
                        <button
                            onClick={handleConfirm}
                            className="flex-1 bg-red-600 hover:bg-red-700 text-white px-4 py-2 rounded"
                        >
                            Confirm
                        </button>
                        <button
                            onClick={() => { setShowConfirm(false); setIsPressed(false); }}
                            className="flex-1 bg-zinc-700 hover:bg-zinc-600 text-white px-4 py-2 rounded"
                        >
                            Cancel
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
}
