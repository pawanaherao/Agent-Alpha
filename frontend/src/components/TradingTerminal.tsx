'use client';

export function TradingTerminal() {
    const handleOpenTerminal = () => {
        // Open tv.dhan.co in a new browser tab (iframe blocked by X-Frame-Options)
        window.open('https://tv.dhan.co', '_blank', 'noopener,noreferrer');
    };

    return (
        <button
            type="button"
            onClick={handleOpenTerminal}
            className="bg-purple-600 hover:bg-purple-700 px-6 py-3 rounded-lg font-bold text-white transition-all flex items-center gap-2 cursor-pointer select-none shadow-lg hover:shadow-purple-500/25"
        >
            📈 Open Trading Terminal
        </button>
    );
}
