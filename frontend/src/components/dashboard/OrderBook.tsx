'use client';

import React, { memo } from 'react';

interface OrderBookProps {
    bids: Array<{ price: number; quantity: number }>;
    asks: Array<{ price: number; quantity: number }>;
}

const OrderRow = memo(({ price, quantity, type }: { price: number; quantity: number; type: 'bid' | 'ask' }) => (
    <div className={`flex justify-between text-xs py-0.5 ${type === 'bid' ? 'text-green-500' : 'text-red-500'}`}>
        <span>{price.toFixed(2)}</span>
        <span>{quantity}</span>
    </div>
));

OrderRow.displayName = 'OrderRow';

export const OrderBook = memo(({ bids, asks }: OrderBookProps) => {
    return (
        <div className="flex flex-col h-64 border border-gray-800 bg-gray-900 rounded-lg p-2">
            <h3 className="text-gray-400 text-xs font-bold mb-2">Order Book</h3>

            <div className="flex-1 overflow-hidden flex gap-2">
                {/* Bids */}
                <div className="flex-1 flex flex-col-reverse overflow-hidden">
                    {bids.slice(0, 15).map((bid, i) => (
                        <OrderRow key={`bid-${i}`} price={bid.price} quantity={bid.quantity} type="bid" />
                    ))}
                </div>

                {/* Asks */}
                <div className="flex-1 flex flex-col overflow-hidden">
                    {asks.slice(0, 15).map((ask, i) => (
                        <OrderRow key={`ask-${i}`} price={ask.price} quantity={ask.quantity} type="ask" />
                    ))}
                </div>
            </div>
        </div>
    );
});

OrderBook.displayName = 'OrderBook';
