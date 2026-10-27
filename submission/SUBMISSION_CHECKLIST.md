# Submission checklist

## Done

- [x] Section 1: design, assumptions and trade-offs in the README
- [x] Section 2: all required endpoints, both bonus features, 43 tests passing on PostgreSQL
- [x] Section 3: live on OCI over HTTPS, with fictional demo data
- [x] Section 4: reflection written

## Still to do

- [ ] Read REFLECTION.md and make sure it is in your own words
- [x] Change the deploy step in `.github/workflows/ci.yml` from Render to OCI
- [ ] Add the deploy key to the server and the secrets/variables to GitHub
- [ ] Fix the GitHub Actions billing lock (github.com/settings/billing)
- [ ] Re-run the checks on PR #1, merge it, and confirm the deploy job turns green
- [ ] Push all changes to GitHub and check the repo is public
- [ ] Just before sending, open `/health` and `/docs` to check the site is up (the IP can change)

## Message to send

Subject: Implementation Engineer Take-Home Assessment – Boniface Mutisya Ngila

Hello Savannah Informatics team,

Please find my CareSlot clinic booking assessment below:

- Repository: https://github.com/BonifaceNgila/CareSlot
- Live API: https://careslot.84-13-134-168.sslip.io/docs
- Health check: https://careslot.84-13-134-168.sslip.io/health

The README covers the design, how to run it locally and the CI/CD setup. My AI reflection is in REFLECTION.md.

Kind regards,
Boniface Mutisya Ngila
