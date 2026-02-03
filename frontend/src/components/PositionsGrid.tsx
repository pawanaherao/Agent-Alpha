'use client';

import { useMemo, useEffect, useState } from 'react';
import { Position } from '@/types';

interface PositionsGridProps {
    positions: Position[];
}

export function PositionsGrid({ positions }: PositionsGridProps) {
    const [AgGridComponent, setAgGridComponent] = useState<any>(null);

    useEffect(() => {
        // Dynamic import to avoid SSR issues
        import('ag-grid-react').then(({ AgGridReact }) => {
            import('ag-grid-community').then(({ ModuleRegistry, AllCommunityModule }) => {
                ModuleRegistry.registerModules([AllCommunityModule]);
                setAgGridComponent(() => AgGridReact);
            });
        });
    }, []);

    const columnDefs = useMemo(() => [
        { field: 'symbol', headerName: 'Symbol', width: 120 },
        { field: 'quantity', headerName: 'Qty', width: 100 },
        { field: 'entryPrice', headerName: 'Entry', width: 120 },
        { field: 'currentPrice', headerName: 'Current', width: 120 },
        { field: 'pnl', headerName: 'P&L', width: 120 },
        { field: 'pnlPercent', headerName: 'P&L%', width: 100 },
        { field: 'strategyName', headerName: 'Strategy', flex: 1 }
    ], []);

    const defaultColDef = useMemo(() => ({
        sortable: true,
        filter: true,
        resizable: true,
    }), []);

    if (!AgGridComponent) {
        return (
            <div className="h-[400px] w-full flex items-center justify-center text-gray-400">
                {positions.length === 0 ? 'No open positions' : 'Loading...'}
            </div>
        );
    }

    if (positions.length === 0) {
        return (
            <div className="h-[400px] w-full flex items-center justify-center text-gray-400">
                No open positions
            </div>
        );
    }

    return (
        <div className="ag-theme-alpine-dark h-[400px] w-full">
            <AgGridComponent
                rowData={positions}
                columnDefs={columnDefs}
                defaultColDef={defaultColDef}
                animateRows={true}
            />
        </div>
    );
}
