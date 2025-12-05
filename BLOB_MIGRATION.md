# Migration to Azure Blob Storage for Direct KB

## 🎯 Overview

Direct Knowledge Base (expert-verified templates and data) now stored in **Azure Blob Storage** instead of local files.

### Benefits

✅ **Centralized**: Single source of truth accessible by all instances  
✅ **Dynamic**: Update templates without redeploying code  
✅ **Versioned**: Blob versioning tracks all changes  
✅ **Scalable**: No deployment size limits  
✅ **Manageable**: Upload/view files directly from UI  

---

## 📋 Setup Instructions

### 1. Create Azure Storage Account & Container

```bash
# Create resource group (if needed)
az group create --name rg-rentready --location westus

# Create storage account
az storage account create \
  --name strentreadykb \
  --resource-group rg-rentready \
  --location westus \
  --sku Standard_LRS

# Get connection string
az storage account show-connection-string \
  --name strentreadykb \
  --resource-group rg-rentready

# Create container (or let the app create it automatically)
az storage container create \
  --name knowledge-base-direct \
  --account-name strentreadykb
```

### 2. Configure Secrets

Add to `.streamlit/secrets.toml`:

```toml
[azure_storage]
connection_string = "DefaultEndpointsProtocol=https;AccountName=strentreadykb;AccountKey=YOUR_KEY_HERE;EndpointSuffix=core.windows.net"
examples_container_name = "knowledge-base-direct"
```

### 3. Sync Local Files to Blob Storage

Run the migration script:

```bash
python sync_examples_to_blob.py
```

This will:
- Upload all files from `examples/` directory
- Preserve directory structure (`sql/`, `definitions/`, etc.)
- Show what was uploaded

---

## 🚀 Usage

### For End Users

**View & Upload via UI**:
1. Open sidebar → "📁 Knowledge Base (direct)"
2. View existing templates by category
3. Upload new templates via upload button
4. Files immediately available to AI agents

### For AI Agents

**Read templates via tool**:

```python
# Read SQL template
read_example(name="перегрузка про", category="sql")

# Read business definitions
read_example(name="metrics", category="definitions")

# Read reference data
read_example(name="status_codes", category="data")
```

### For Developers

**Manage files programmatically**:

```python
from src.storage.blob_examples import BlobExamplesManager

# Initialize
blob_manager = BlobExamplesManager(
    connection_string="...",
    container_name="knowledge-base-direct"
)

# List files
blobs = blob_manager.list_blobs(category="sql")

# Read file
content = blob_manager.read_blob("sql/pro_load_calculation.sql")

# Upload file
blob_manager.upload_blob(
    content="SELECT ...",
    relative_path="sql/new_query.sql",
    overwrite=True
)

# Delete file
blob_manager.delete_blob("sql/old_query.sql")
```

---

## 📁 Directory Structure in Blob

```
knowledge-base-direct (container)
└── examples/
    ├── sql/
    │   ├── pro_load_calculation.sql
    │   └── ...
    ├── definitions/
    │   └── metrics.md
    ├── scripts/
    │   └── ...
    └── data/
        └── ...
```

---

## 🔧 Troubleshooting

### Error: "Could not access Azure Blob Storage"

**Check**:
1. Connection string is correct in `secrets.toml`
2. Storage account exists and is accessible
3. Container name matches configuration

### Files not showing in UI

**Solutions**:
1. Run `sync_examples_to_blob.py` to upload local files
2. Check container name in configuration
3. Verify files are in correct path structure (`examples/category/file.ext`)

### Upload fails

**Check**:
1. File format is supported (`.sql`, `.md`, `.txt`, `.json`, `.py`, `.yaml`, `.csv`, `.xml`)
2. File size is reasonable (<50MB)
3. Storage account has write permissions

---

## 🔄 Backward Compatibility

**Local files**: The `examples/` directory remains in git for reference and backup. However, the application now reads from blob storage.

**Migration path**:
1. Keep local files as backup
2. Sync to blob storage once
3. Future updates via UI or directly in blob storage
4. Optional: Remove local `examples/` from repo later

---

## 📊 Monitoring

View blob storage metrics in Azure Portal:
- Container → Metrics
- Track: Transactions, Ingress, Egress
- Set up alerts for unusual activity

---

## 🎓 Best Practices

1. **Version Control**: Enable blob versioning for audit trail
2. **Access Control**: Use SAS tokens or managed identities (not connection strings in production)
3. **Backup**: Set up geo-redundant storage (GRS) for critical templates
4. **Naming**: Use descriptive filenames (`pro_load_calculation.sql` not `query1.sql`)
5. **Categories**: Organize into clear categories (`sql`, `definitions`, `scripts`, `data`)

---

## 📝 Next Steps

After migration:
1. ✅ Verify all files uploaded correctly
2. ✅ Test reading via UI
3. ✅ Test AI agents using `read_example()` tool
4. ✅ Add new templates via UI (no code changes needed!)
5. 🎉 Enjoy centralized, dynamic knowledge base!

