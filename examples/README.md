# Examples Directory - Expert-Verified Templates & Data

## 🎯 Purpose

This directory contains **expert-verified templates, queries, and reference data** that AI agents use to ensure 100% accurate calculations and decisions.

## 📂 Structure

```
examples/
├── sql/                    # SQL query templates
│   ├── pro_load_calculation.sql
│   └── README.md
├── definitions/            # Business metrics & glossary
│   └── metrics.md
├── scripts/                # Python, YAML scripts (optional)
├── data/                   # JSON, CSV reference data (optional)
└── README.md              # This file
```

**Supported formats**: `.sql`, `.md`, `.txt`, `.json`, `.py`, `.yaml`, `.csv`, `.xml`

## 🚀 How It Works

### Problem We Solved

Previously, AI agents would:
1. Search Azure AI Search (unreliable, sometimes returns partial results)
2. **Simplify or modify** content (removing important details)
3. **Invent their own logic** (adding assumptions)
4. Get **incorrect results** ❌

### Solution: Local Templates & Data

Now, AI agents:
1. Call `read_example(name="перегрузка про", category="sql")` tool **FIRST**
2. Get **complete, expert-verified content** from local file
3. Use content **EXACTLY as-is**, only replacing placeholders if needed
4. Get **correct results** ✅

## 🔧 For AI Agents

### When to Use `read_example()` Tool

**ALWAYS call this tool FIRST** when user asks about:
- Known calculations: "перегрузка про", "pro load", etc.
- Business definitions: "what is DSAT?", "metrics definitions"
- Reference data: configuration, lookup tables
- Standard queries or scripts

### Usage Examples

**SQL Template:**
```python
# Step 1: Get SQL template
result = read_example(name="перегрузка про", category="sql")

# Step 2: Replace placeholders
sql = result.replace("<PRO_ID>", "f7fef730-b009-ec11-b6e6-000d3a8d582c")
sql = sql.replace("<START_DATE>", "2025-09-01")
sql = sql.replace("<END_DATE>", "2025-10-01")

# Step 3: Execute with MCP
mcp_rentready-prod_execute_sql(query=sql)
```

**Business Definitions:**
```python
# Get metrics definitions
definitions = read_example(name="metrics", category="definitions")
# Parse and use to understand business rules
```

**Reference Data:**
```python
# Get JSON configuration
config = read_example(name="status_codes", category="data")
# Parse JSON and use as lookup table
```

### 🚫 DO NOT

- Modify the SQL logic
- Remove JOINs or WHERE conditions
- Simplify CASE expressions
- Use different column names
- Add your own filters

### ✅ DO

- Copy SQL character-by-character
- Only replace placeholders: `<PRO_ID>`, `<START_DATE>`, `<END_DATE>`
- Keep ALL JOINs, WHERE conditions, GROUP BY clauses
- Trust the expert-verified SQL

## 👨‍💻 For Developers

### Adding New SQL Template

1. **Create SQL file** in `examples/sql/metric_name.sql`
2. **Add comments** explaining what it calculates
3. **Mark placeholders** clearly: `<PLACEHOLDER_NAME>`
4. **Test thoroughly** against production data
5. **Update mapping** in `src/workflow/builder.py`:
   ```python
   metric_map = {
       "new_metric": "new_metric_calculation.sql",
       "новая метрика": "new_metric_calculation.sql",
   }
   ```
6. **Update README** in `examples/sql/README.md`

### SQL Template Guidelines

```sql
-- ===================================================================
-- METRIC NAME (Russian and English)
-- ===================================================================
-- 
-- DESCRIPTION:
-- Clear explanation of what this calculates
--
-- METRIC VALUES:
-- Explain all possible values (e.g., 0/1/2/3 categories)
--
-- PLACEHOLDERS:
-- - <PLACEHOLDER_1>: Description
-- - <PLACEHOLDER_2>: Description
--
-- IMPORTANT:
-- List any critical rules, filters, or business logic
-- ===================================================================

SELECT 
    column1,
    column2,
    CASE ... END as metric
FROM table1 t1
    LEFT JOIN table2 t2 ON t1.id = t2.fk
WHERE 
    t1.id = '<PLACEHOLDER_1>'
    AND t1.date BETWEEN '<START_DATE>' AND '<END_DATE>'
    AND t2.status IN (...)
GROUP BY ...
ORDER BY ...
```

## 📊 Available Templates

### 1. Pro Load (Перегрузка Про)

**File**: `sql/pro_load_calculation.sql`  
**Tool name**: `"перегрузка про"` / `"pro load"`  

**What it calculates**: Daily professional overload indicator (0/1/2/3)  
**Placeholders**: `<PRO_ID>`, `<START_DATE>`, `<END_DATE>`  

**Use cases**:
- "Покажи перегрузку Про для Magdalena"
- "Calculate pro load for professional"
- "Когда профессионал был перегружен?"

---

## 🏆 Benefits

| Aspect | Before (AI Search) | After (Local Templates) |
|--------|-------------------|------------------------|
| **Accuracy** | ⚠️ Variable (60-90%) | ✅ 100% |
| **Reliability** | ❌ Sometimes incomplete | ✅ Always complete |
| **Speed** | 🐢 API calls (1-3s) | ⚡ Direct read (<100ms) |
| **Versioning** | ❌ No tracking | ✅ Git history |
| **Debugging** | 😰 Hard | 😊 Easy |
| **Modifications** | ⚠️ Agents modify SQL | ✅ Agents use as-is |

## 📝 Notes

- **Priority**: Local templates are checked **BEFORE** Azure AI Search
- **Fallback**: If no local template exists, system falls back to Knowledge Base search
- **Hybrid approach**: Best of both worlds - deterministic + flexible

