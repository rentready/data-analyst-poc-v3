-- ===================================================================
-- PRO LOAD CALCULATION (Расчёт перегрузки профессионала)
-- ===================================================================
-- 
-- DESCRIPTION:
-- This query calculates the daily pro_load metric for a professional.
-- It compares actual bookings against the professional's capacity (maxcap).
--
-- METRIC VALUES:
-- 0 = No bookings
-- 1 = Low load (bookings < maxcap)
-- 2 = Normal load (bookings = maxcap)
-- 3 = OVERLOAD (bookings > maxcap)
--
-- IMPORTANT: Use this SQL EXACTLY as-is. Only replace placeholders:
-- - <PRO_ID>: Professional's bookableresourceid
-- - Date range in WHERE clause
--
-- DO NOT:
-- - Remove any JOIN or WHERE conditions
-- - Simplify the CASE expression
-- - Change column names or aggregations
-- ===================================================================

SELECT 
    CONVERT(DATE, brb.starttime) as date,
    brb.resourcename,
    r.rr_lucasnumber as maxcap,
    SUM(brb.rr_lucasnumbertotal) as bookings,
    CASE
        WHEN SUM(brb.rr_lucasnumbertotal) IS NULL OR SUM(brb.rr_lucasnumbertotal) = 0 THEN 0
        WHEN SUM(brb.rr_lucasnumbertotal) > 0 AND SUM(brb.rr_lucasnumbertotal) < r.rr_lucasnumber THEN 1
        WHEN SUM(brb.rr_lucasnumbertotal) = r.rr_lucasnumber THEN 2
        WHEN SUM(brb.rr_lucasnumbertotal) > r.rr_lucasnumber THEN 3
    END as pro_load
FROM bookableresourcebooking brb
    LEFT JOIN bookableresource r ON brb.resource = r.bookableresourceid
    LEFT JOIN msdyn_workorder wo ON wo.msdyn_workorderid = brb.msdyn_workorder
WHERE 
    brb.resource = '<PRO_ID>'
    AND brb.starttime BETWEEN '<START_DATE>' AND '<END_DATE>'
    AND wo.msdyn_systemstatus IN (690970004, 690970003, 690970002, 690970001)
    AND wo.statuscode = 1
    AND wo.rr_workscheduleddate IS NOT NULL
    AND brb.bookingstatus = 'c33410b9-1abe-4631-b4e9-6e4a1113af34'
GROUP BY 
    CONVERT(DATE, brb.starttime),
    brb.resourcename,
    r.rr_lucasnumber
ORDER BY date

