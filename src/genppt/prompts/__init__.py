"""GenPPT prompt registry — externalized System Prompts.

To migrate hardcoded prompts to editable YAML files:
    python -m genppt.prompts bootstrap
"""

from .loader import get_prompt, get_prompt_version, list_prompt_versions, bootstrap_prompt_files

__all__ = ["get_prompt", "get_prompt_version", "list_prompt_versions", "bootstrap_prompt_files"]

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "bootstrap":
        results = bootstrap_prompt_files(dry_run=False)
        for agent, created in results.items():
            print(f"  {'✅' if created else '⏭️'} {agent}")
        print("Done.")
    else:
        print("Usage: python -m genppt.prompts bootstrap")
