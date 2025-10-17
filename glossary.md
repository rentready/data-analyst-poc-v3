BUSINESS TERMS & DEFINITIONS:

**Work Order (msdyn_workorder)** - A service request for property maintenance or repair. Contains service type, property, dates, status, and assigned resources.

**DSAT (Dissatisfaction)** - Customer dissatisfaction metric stored in table 'incident' (also referenced as a 'case'). To get DSAT records, filter by rr_casetype = 315740000. Used to track service quality complaints.

**Job Profile (rr_jobprofile), also referrenced as a Turn** - Template for common work order types with predefined settings, pricing, and service details. Linked to work orders via rr_jobprofileid.

**Service Account** - Property management company or organization that requests services. The client/customer in the system.

**Management Company** - Property management organization that manages properties. Stored in 'account' table with the field rr_accounttype = 315740002. Related to properties and work orders. Referenced by field parentaccountid by properties (account record). Metrics should be queried by individual property linked to it.

**Market** - Geographic or business market segment. Stored in 'msdyn_organizationalunit' table. Used to organize and segment business operations by region or market area.

**Invoice** - Billing document for completed work orders. Contains pricing, payment status, and financial details.

**Property (account)** - Physical location where service is performed. Stored in account table, linked to work orders and job profiles. Has also parentaccountid field with a reference to the management company (account record). When search by name, apply to searches: by management company and by normal account name.

**Work Order Service (msdyn_workorderservice)** - Individual service line item within a work order. One work order can have multiple services.
