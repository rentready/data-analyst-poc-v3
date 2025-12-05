# SQL Query Examples

This directory contains **expert-verified SQL queries** for calculating business metrics in RentReady system.

## 📋 Purpose

These SQL templates are designed to be used **EXACTLY AS-IS** by AI agents. They contain:
- Correct JOIN conditions
- Proper filtering logic
- Validated business rules
- Optimal performance patterns

## 🚨 Critical Rules for AI Agents

When using these SQL templates:

1. **COPY EXACTLY** - Do not simplify, optimize, or modify the SQL logic
2. **REPLACE ONLY PLACEHOLDERS**:
   - `<PRO_ID>` → actual professional ID
   - `<START_DATE>` and `<END_DATE>` → actual date range
   - `<PROPERTY_ID>` → actual property ID
3. **KEEP ALL CONDITIONS** - Every JOIN, WHERE clause, and filter is there for a reason
4. **DO NOT**:
   - Remove JOINs (even if they seem redundant)
   - Simplify CASE expressions
   - Change aggregations (SUM, COUNT, etc.)
   - Modify status codes or filter values

## 📁 Available Templates

### `pro_load_calculation.sql`

**When to use**: Calculate "перегрузка Про" (professional overload) metric

**Placeholders**:
- `<PRO_ID>` - Professional's `bookableresourceid`
- `<START_DATE>` - Start date (format: 'YYYY-MM-DD')
- `<END_DATE>` - End date (format: 'YYYY-MM-DD')

**Returns**:
- `date` - Date of bookings
- `resourcename` - Professional's name
- `maxcap` - Maximum capacity (from rr_lucasnumber)
- `bookings` - Actual bookings count
- `pro_load` - Load indicator (0/1/2/3)

**Related terms**: 
- перегрузка Про
- про лоад
- pro load
- professional overload
- загрузка профессионала

---

## 🔧 For Developers

When adding new SQL templates:

1. **Test thoroughly** against production data
2. **Document placeholders** clearly
3. **Include business context** (what metric it calculates)
4. **Add validation rules** (what values are expected)
5. **Update this README** with the new template

## 📚 Related Resources

- Business metrics definitions: `examples/definitions/metrics.md`
- Database schema: See Azure SQL Database documentation
- Entity relationships: See MCP server documentation

