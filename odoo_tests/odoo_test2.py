import xmlrpc.client
import os
from dotenv import load_dotenv

# 1. Load your .env file
load_dotenv()

# --- CONFIGURATION (Mapped to your .env) ---
url = os.getenv('ODOO_URL', 'http://localhost:8069')
db = os.getenv('ODOO_DB')            # Should be 'my_dev_db'
username = os.getenv('ODOO_ADMIN_USER')
password = os.getenv('ODOO_ADMIN_PASSWORD')

# --- INITIAL HANDSHAKE ---
try:
    common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
    uid = common.authenticate(db, username, password, {})
    
    if not uid:
        print(f"❌ Auth Failed: Check password for '{username}' in .env")
        exit()
        
    print(f"✅ Connected to Odoo! User ID (UID): {uid}")

except Exception as e:
    print(f"💥 Connection Error: {e}")
    exit()

# --- DATA INTERACTION ---
models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')

# --- STEP 1: Find Azure Interior's ID ---
# We need the ID from res.partner to search for their invoices
azure_domain = [('name', '=', 'Azure Interior')]
azure_id = models.execute_kw(db, uid, password, 'res.partner', 'search', [azure_domain])

if not azure_id:
    print("❌ Could not find a partner named 'Azure Interior'.")
    exit()

# --- STEP 2: Find their Invoices ---
# move_type 'out_invoice' = Customer Invoice
# state 'posted' = Confirmed (not a draft)
invoice_domain = [
    ('partner_id', '=', azure_id[0]),
    ('move_type', '=', 'out_invoice'),
    ('state', '=', 'posted')
]

invoice_ids = models.execute_kw(db, uid, password, 'account.move', 'search', [invoice_domain])

# --- STEP 3: Read and Display Invoice Data ---
if invoice_ids:
    # We pull the fields you saw on the Odoo screen earlier
    invoice_fields = {
        'fields': ['name', 'invoice_date', 'amount_total', 'amount_residual', 'currency_id']
    }
    invoices = models.execute_kw(db, uid, password, 'account.move', 'read', [invoice_ids], invoice_fields)
    
    print(f"\n💰 INVOICE REPORT FOR: Azure Interior (ID: {azure_id[0]})")
    print("-" * 70)
    print(f"{'Invoice Number':<20} | {'Date':<12} | {'Total Amount':<12} | {'Still Owed'}")
    print("-" * 70)
    
    for inv in invoices:
        number = inv.get('name')
        date = inv.get('invoice_date')
        total = f"{inv.get('amount_total'):,.2f}"
        due = f"{inv.get('amount_residual'):,.2f}"
        # currency_id usually returns [id, "USD"]
        currency = inv.get('currency_id')[1] if inv.get('currency_id') else ""
        
        print(f"{number:<20} | {date:<12} | {total:>10} {currency} | {due:>10} {currency}")
else:
    print(f"ℹ️ No posted invoices found for Azure Interior (ID: {azure_id[0]}).")