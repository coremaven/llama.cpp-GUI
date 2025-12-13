#!/usr/bin/env python3
"""
Simple script to inspect the saved configuration file
"""

import json
from pathlib import Path

config_file = Path.home() / ".llama_server_gui_config.json"

if config_file.exists():
    with open(config_file, 'r') as f:
        config = json.load(f)

    print("=== Configuration File Contents ===")
    print(f"File: {config_file}")
    print(f"\nLast Profile: {config.get('last_profile', 'None')}")
    print(f"\nNumber of Profiles: {len(config.get('profiles', {}))}")

    profiles = config.get('profiles', {})
    if profiles:
        print("\n=== Profiles ===")
        for name, settings in profiles.items():
            print(f"\nProfile: {name}")
            for key, value in settings.items():
                print(f"  {key}: {value}")
    else:
        print("\nNo profiles saved yet")
else:
    print(f"Configuration file not found: {config_file}")
