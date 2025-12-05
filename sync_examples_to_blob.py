"""Sync local examples to Azure Blob Storage - One-time migration script."""

import os
import sys
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.storage.blob_examples import BlobExamplesManager

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def main():
    """Sync local examples directory to Azure Blob Storage."""
    
    print("=" * 70)
    print("SYNC LOCAL EXAMPLES TO AZURE BLOB STORAGE")
    print("=" * 70)
    print()
    
    # Get configuration
    try:
        import toml
        
        # Load secrets
        secrets_path = Path(".streamlit/secrets.toml")
        if not secrets_path.exists():
            print(f"❌ ERROR: secrets.toml not found at {secrets_path}")
            print("Please create .streamlit/secrets.toml with azure_storage configuration")
            return 1
        
        secrets_data = toml.load(secrets_path)
        
        connection_string = secrets_data["azure_storage"]["connection_string"]
        container_name = secrets_data["azure_storage"]["examples_container_name"]
        
    except KeyError as e:
        print(f"❌ ERROR: Missing configuration key: {e}")
        print("\nMake sure .streamlit/secrets.toml has [azure_storage] section with:")
        print("  - connection_string")
        print("  - examples_container_name")
        return 1
    except Exception as e:
        print(f"❌ ERROR loading configuration: {e}")
        return 1
    
    # Initialize blob manager
    print(f"📦 Connecting to Azure Blob Storage...")
    print(f"   Container: {container_name}")
    print()
    
    try:
        blob_manager = BlobExamplesManager(
            connection_string=connection_string,
            container_name=container_name
        )
        print("✅ Connected to Azure Blob Storage")
        print()
    except Exception as e:
        print(f"❌ ERROR connecting to blob storage: {e}")
        return 1
    
    # Get local examples directory
    examples_dir = Path(__file__).parent / "examples"
    
    if not examples_dir.exists():
        print(f"❌ ERROR: Local examples directory not found: {examples_dir}")
        return 1
    
    print(f"📁 Local examples directory: {examples_dir}")
    print()
    
    # Confirm before proceeding
    response = input("⚠️  This will upload/overwrite files in blob storage. Continue? (yes/no): ")
    if response.lower() not in ['yes', 'y']:
        print("❌ Cancelled by user")
        return 0
    
    print()
    print("🔄 Syncing files...")
    print("-" * 70)
    
    # Sync files
    try:
        uploaded, errors = blob_manager.sync_from_local(examples_dir)
        
        print("-" * 70)
        print()
        print(f"✅ Sync completed!")
        print(f"   Uploaded: {uploaded} files")
        if errors > 0:
            print(f"   Errors: {errors} files")
        print()
        
        # List what's now in blob storage
        print("📋 Files in blob storage:")
        blobs = blob_manager.list_blobs()
        
        if blobs:
            categories = {}
            for blob in blobs:
                cat = blob['category']
                if cat not in categories:
                    categories[cat] = []
                categories[cat].append(blob['filename'])
            
            for category, files in sorted(categories.items()):
                print(f"\n  📂 {category}/")
                for filename in sorted(files):
                    print(f"     - {filename}")
        else:
            print("  (no files)")
        
        print()
        print("🎉 Done! Files are now available in Azure Blob Storage.")
        print("   AI agents will access them via the read_example() tool.")
        
        return 0
    
    except Exception as e:
        print(f"❌ ERROR during sync: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

