#!/usr/bin/env python3
"""
Startup Validation Script
Checks if all required configurations are in place before starting the application.
"""

import os
import sys
from pathlib import Path

def check_env_file(filepath: str, required_vars: list) -> bool:
    """Check if .env file exists and has required variables."""
    if not os.path.exists(filepath):
        print(f"❌ {filepath} NOT FOUND")
        return False
    
    print(f"✅ {filepath} exists")
    
    with open(filepath, 'r') as f:
        content = f.read()
        missing = [var for var in required_vars if var not in content]
        
        if missing:
            print(f"   ⚠️  Missing variables: {missing}")
            return False
    
    return True

def check_file_exists(filepath: str) -> bool:
    """Check if a file exists."""
    if not os.path.exists(filepath):
        print(f"❌ {filepath} NOT FOUND")
        return False
    print(f"✅ {filepath} exists")
    return True

def main():
    print("\n" + "="*70)
    print("🔍 AGENTIC ALPHA - STARTUP VALIDATION")
    print("="*70 + "\n")
    
    checks_passed = 0
    checks_total = 0
    
    # Check environment files
    print("📋 Checking environment files...")
    checks = [
        ("backend/.env", ["POSTGRES_USER", "POSTGRES_PASSWORD", "REDIS_HOST"]),
        ("frontend/.env.local", ["NEXT_PUBLIC_API_URL"]),
    ]
    
    for filepath, required in checks:
        checks_total += 1
        if check_env_file(filepath, required):
            checks_passed += 1
    
    print()
    
    # Check database files
    print("🗄️  Checking database configuration...")
    checks_total += 1
    if check_file_exists("backend/db/init.sql"):
        checks_passed += 1
    
    print()
    
    # Check Docker files
    print("🐳 Checking Docker configuration...")
    checks = ["docker-compose.yml", "backend/Dockerfile", "frontend/Dockerfile"]
    for filepath in checks:
        checks_total += 1
        if check_file_exists(filepath):
            checks_passed += 1
    
    print()
    
    # Summary
    print("="*70)
    print(f"✅ VALIDATION SUMMARY: {checks_passed}/{checks_total} checks passed")
    print("="*70 + "\n")
    
    if checks_passed == checks_total:
        print("🚀 All checks passed! Ready to start local environment.\n")
        print("Next steps:")
        print("  1. Run: docker-compose build")
        print("  2. Run: docker-compose up")
        print("  3. Wait for all services to show 'healthy'")
        print("  4. Visit: http://localhost:3000 (frontend)")
        print("  5. Visit: http://localhost:8000/docs (API docs)\n")
        return 0
    else:
        print(f"❌ Some checks failed ({checks_total - checks_passed} issues found)\n")
        print("Please fix the issues above and run this script again.\n")
        return 1

if __name__ == "__main__":
    sys.exit(main())
