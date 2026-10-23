# TDLR TABS data-center registrations (statewide Texas)

**Status: enabled.** On October 23, 2026 `SearchProjects` returned JSON for a 90-day "data center" search (12 rows). Project page TABS2027003697 parsed with the existing page parser. A full scheduled run from the deployed environment has not been repeated.


- **Publisher:** the Texas Department of Licensing and Regulation, Architectural Barriers program (TABS). Commercial projects of $50,000 or more must register, inside or outside city limits, so TABS covers unincorporated county land that city permit tables miss.
- **Search:** the public project search page posts to `/TABS/Search/SearchProjects`. The form uses the DataTables server-side protocol with `ProjectName` and `RegistrationDateBegin`.
  - The adapter runs one search per configured name term ("data center", "datacenter") over the last 90 days, in pages of 100.
  - The run fails if a term matches more than 300 projects, if a page is empty before the reported total, or if any row is malformed.
- **Project pages:** each project page (`/TABS/Search/Project/<number>`) supplies:
  - registration date and status
  - address and county
  - developer-reported start and completion dates
  - estimated cost, type of work and scope
  - owner and design firm

  A project is kept only when its name, facility or scope names a data center. The run fails if any project is registered after the run date.
- **Admission (`tdlr-tabs-data-center-v1`):** New Construction or Additions to Existing Building becomes a Signal.
  - Rejected: renovations; "Project Closed" or "Inspection Complete(d)" statuses; and projects whose reported completion date has already passed.
  - The reason states that start, completion and cost are the registrant's estimates. MW appears only when the scope states it.
- **Real-source evidence (indexed project pages, retrieved 2026-10-14):**

  | Registration | Project | Location | Estimated cost | Notes |
  |---|---|---|---|---|
  | TABS2026009183 | Databank Red Oak DFW13 | Ellis County | $325M | Registered 2026-01-05; start 2026-03-01, completion 2027-12-31; owner DB Data Center Red Oak, LLC |
  | TABS2026005307 | CyrusOne DFW17B | Bosque County | $500M | |
  | TABS2026023619 | BT Gateway | Hunt County | $384M | |
  | TABS2026001234 | Vantage TX12 | Bexar County | $277M | Scope states "up to 96MW critical IT" |
  | TABS2024023976 | SAT82 | Medina County | $483M | |

- **Limitations:**
  - Registration is accessibility review, not a building permit or construction start.
  - Projects named without a data-center term are missed.
  - On October 23, 2026 the SearchProjects POST for "data center" returned 12 JSON rows, and project page TABS2027003697 parsed as a Compass Datacenters renovation in Ellis County. The unit-test search fixture is still the recorded column contract, not that live response. A full scheduled run that opens every project page has not been repeated.
- Signals from this source are labelled "Official TDLR project registration", not "Official permit".
