# Business Metrics Definitions

This file contains definitions of key business metrics used in RentReady system.

---

## Pro Load (Перегрузка Про)

**Business Name**: Перегрузка профессионала  
**Technical Name**: `pro_load`  
**SQL Template**: `examples/sql/pro_load_calculation.sql`

### Description

Pro Load measures how much a professional's daily workload exceeds their capacity. It helps identify overworked professionals who may need support.

### Calculation

Compares daily bookings against professional's maximum capacity (MaxCap):

```
pro_load = CASE
    WHEN bookings = NULL OR bookings = 0 THEN 0
    WHEN bookings > 0 AND bookings < maxcap THEN 1
    WHEN bookings = maxcap THEN 2
    WHEN bookings > maxcap THEN 3
END
```

### Values

| Value | Category | Description |
|-------|----------|-------------|
| 0 | Нет букингов | No bookings for the day |
| 1 | Низкая загрузка | Low load (below capacity) |
| 2 | Нормальная нагрузка | Normal load (at capacity) |
| 3 | **Перегрузка** | **OVERLOAD** (exceeds capacity) |

### Data Sources

- **Bookings**: `bookableresourcebooking.rr_lucasnumbertotal` (sum per day)
- **MaxCap**: `bookableresource.rr_lucasnumber`
- **Filters**: Only active work orders with specific statuses

### Important Notes

⚠️ **Do NOT use simple booking count!**  
- Incorrect: `COUNT(*)`
- Correct: `SUM(brb.rr_lucasnumbertotal)`

⚠️ **Must filter by work order status!**  
Required conditions:
- `wo.msdyn_systemstatus IN (690970004, 690970003, 690970002, 690970001)`
- `wo.statuscode = 1`
- `wo.rr_workscheduleddate IS NOT NULL`
- `brb.bookingstatus = 'c33410b9-1abe-4631-b4e9-6e4a1113af34'`

### Related Terms

- Загрузка профессионала
- Professional overload
- Pro capacity
- MaxCap
- Lucas Number

---

## [Future metrics will be added here]

---

## Notes for AI Agents

When asked about metrics:
1. **Check this file first** for definitions
2. **Use exact SQL from templates** in `examples/sql/`
3. **Do not invent formulas** - always reference documented calculations
4. **Preserve all filters** - they exist for data quality reasons

