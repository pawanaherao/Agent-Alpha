import asyncio
import logging
import sys
import os

# Add parent directory to path to import src
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), '..')))

from src.agents.sentiment import SentimentAgent

# Configure logging
logging.basicConfig(level=logging.INFO)

async def test_sentiment():
    agent = SentimentAgent()
    await agent.start()
    
    # Test headlines
    headlines = [
        {"headline": "NIFTY 50 surges to record high as FII inflows accelerate"},
        {"headline": "Market crash imminent as inflation fears grip investors"},
        {"headline": "RBI keeps rates unchanged, stance remains accommodative"},
        {"headline": "Global markets trading flat ahead of US jobs data"}
    ]
    
    score = await agent._analyze_with_rules(headlines)
    classification = agent._classify_sentiment(score)
    
    print(f"\n=== Sentiment Agent Test ===")
    print(f"Overall Score: {score:.4f}")
    print(f"Classification: {classification}")
    
    # Test individual headlines via Vader
    if agent.analyzer:
        print("\nIndividual Sentence Analysis:")
        for h in headlines:
            s = agent.analyzer.polarity_scores(h['headline'])
            print(f"- {h['headline']:50} | Compound: {s['compound']:>7.4f}")
    else:
        print("\nVader not available, using keyword fallback.")

if __name__ == "__main__":
    asyncio.run(test_sentiment())
