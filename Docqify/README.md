# Docqifyon Vercel

This folder is a Vercel-ready copy of the Docqifyapp.

## Included

- `main.py`: Flask app entrypoint for Vercel
- `templates/`: all HTML templates
- `public/static/js/download-payment.js`: static payment helper
- `requirements.txt`: Python dependencies
- `vercel.json`: Vercel function config
- `.python-version`: Python runtime version

## Important deployment notes

- Static assets are served from `public/**`, which matches Vercel's Python runtime guidance.
- Writable files are stored in `/tmp/Docqify` on Vercel.
- PDF generation uses `wkhtmltopdf` when available and falls back to `xhtml2pdf` on Vercel.
- Analytics/settings stored in SQLite or JSON inside `/tmp` are temporary on serverless infrastructure.

For real production persistence, move analytics, admin settings, and payments metadata to an external database or managed storage.

## Environment variables to set in Vercel

- `FLASK_SECRET_KEY`
- `ADMIN_PASSWORD`
- `AI_PROVIDER`
- `AI_MODEL`
- `GEMINI_API_KEY`
- `OPENAI_API_KEY`
- `RAZORPAY_KEY_ID`
- `RAZORPAY_KEY_SECRET`
- `DOCUMENT_PRICE`
- `PAYMENT_CURRENCY`
- `AI_USAGE_ENABLED`
- `DOCUMENT_RULES_JSON`

## Example `DOCUMENT_RULES_JSON`

```json
{
  "/resume": { "price": "19.00", "token_limit": 1200 },
  "/sop": { "price": "49.00", "token_limit": 2200 },
  "/tender_document": { "price": "79.00", "token_limit": 2600 }
}
```

## Deploy steps

1. Upload the `Docqify` folder as the Vercel project root.
2. Add the environment variables in the Vercel dashboard.
3. Deploy.
4. After deploy, open `/admin/login` and use the `ADMIN_PASSWORD`.

## References

- Vercel Python runtime docs: https://vercel.com/docs/functions/runtimes/python
