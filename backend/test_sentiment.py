"""
Test Sentiment Agent News and GenAI Capabilities
"""
import asyncio
import sys
sys.stdout.reconfigure(encoding='utf-8')

from src.agents.sentiment import SentimentAgent


async def test_sentiment():
    print("=" * 60)
    print("SENTIMENT AGENT TEST")
    print("=" * 60)
    
    agent = SentimentAgent("SentimentTest")
    
    # Start agent (initializes GenAI)
    await agent.start()
    
    print(f"\nGenAI Enabled: {agent.model is not None}")
    
    # Test analyze
    print("\n[Analyzing Market Sentiment...]")
    score = await agent.analyze()
    
    print(f"\nGlobal Sentiment Score: {score:.2f}")
    
    # Get summary
    summary = agent.get_sentiment_summary()
    
    print(f"\nClassification: {summary['classification']}")
    print(f"Headline Count: {summary['headline_count']}")
    print(f"GenAI Enabled: {summary['genai_enabled']}")
    
    print("\n[Top Headlines]")
    for i, h in enumerate(summary.get('top_headlines', [])[:5], 1):
        print(f"  {i}. {h[:70]}...")
    
    # Test stock-specific
    print("\n[Testing Stock-Specific Sentiment (RELIANCE)]")
    stock_score = await agent.analyze_stock_sentiment("RELIANCE")
    print(f"RELIANCE Sentiment: {stock_score:.2f}")
    
    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)
    
    return score


if __name__ == "__main__":
    asyncio.run(test_sentiment())
