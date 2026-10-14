# Public stock dashboard

This page is intentionally public: anyone with its link can view and change the portfolio.

## Contents

- `site/`: the web page, with the holdings table, add/update form and pie chart.
- `local_server.py`: a local server that serves the page and stores holdings in `web/holdings.json`.
- `api/`: the Lambda backend for AWS.
- `infra/`: the CDK code that deploys the page and the backend to AWS.
- `README.md`: deploy notes.

## Deploy

1. Create a Finnhub API key and keep it private.
2. In `web/infra`, create a Python virtual environment, install `-r requirements.txt`, then run `cdk bootstrap` (once) and `cdk deploy`.
3. Give the key when CDK asks for `FinnhubApiKey`.
4. Copy the printed `ApiUrl` into `web/site/app.js` in place of `REPLACE_WITH_API_URL`, then run `cdk deploy` again.

The deployment prints the CloudFront URL for the website. It stores holdings in DynamoDB and deletes nothing automatically on stack removal.
