# Scripts
|File|Purpose|Command|
| -------- | -------- | -------- |
|pull_shopify_data.py|Pull the most recent data while keeping handle, title, and vendor|python pull_shopify_data.py --products plan_products.csv --variants plan_variants.csv --limit 500 --offset 0|
|push_plan_to_shopify.py|Push products and variants to Shopify using existing products|python push_plan_to_shopify.py --products plan_products.csv --variants plan_variants.csv --limit 25 --test --apply|
|webami_fetch.py|Fetch product data|python webami_fetch.py --offset 0 --limit 100|
|webami_push.py|Push new webami data to Shopify|python webami_push.py --offset 0 --limit 25 --apply|
|price_tools.py|Pulls prices of products from Shopify|python price_tools.py report|
|price_tools.py|Update prices in Shopify by increased or decreased prices|python price_tools.py apply --file price_increases.csv --apply|



---

# Environment Setup
## Mac
```
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Windows (Powershell)
```
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```