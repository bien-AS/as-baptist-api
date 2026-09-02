# Issue Tracker

## System of record

Issues for this repository live as work items in the shared Plane project **baptist** (the project previously surfaced as “Baptist Work Items”) in workspace `saas-dev`.

- Project page: `https://dev-plane.michaelkorsdiaperbagonsale.us/saas-dev/projects/45331253-c9ba-44c1-bfed-976c87ff13c0/issues/`
- API base: `https://dev-plane.michaelkorsdiaperbagonsale.us/api/v1/workspaces/saas-dev/projects/45331253-c9ba-44c1-bfed-976c87ff13c0`
- List/create work items: `GET`/`POST` `/work-items/`
- Retrieve/update/delete a work item: `/work-items/<work-item-id>/`
- Authentication: send the Plane API key in `X-API-Key`.

In this workspace, read only the Plane section of `..\..\plane-creds.md`. Never print, commit, copy, or embed the key in source. Other environments must provide the key through a secure secret such as `PLANE_API_KEY`.

## Workflow

- Plane is the request surface; do not create GitHub Issues for this repository unless the tracker configuration is explicitly changed.
- New build-pack work items use the title form `[KEY] Summary`, `external_source=build-pack`, and `external_id=KEY`.
- New imported work starts in `Backlog` unless the work item has an explicit state.
- Preserve the build-pack metadata, test scenarios, and pass criteria in the work-item description.
- Pull requests are not automatically treated as new tickets; link them to the relevant Plane work item.
- The former Baptist work items were archived during the migration. Do not revive them without an explicit request.

## Repository mapping

This repository maps to the build-pack `Repo` value `baptist-api`. Tickets with `Repo=all` or `Repo=all four` may also affect it; consult the ticket description and dependencies before implementation.

Build-pack labels are `parallel-safe`, `gate`, `security`, `money`, and `phi`. Triage labels are documented in `triage-labels.md`.
