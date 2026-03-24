import xmlrpc.client
import os
from dotenv import load_dotenv

# Load the environment variables from your .env file
load_dotenv()

# --- CONFIGURATION ---
# Using the APPLICATION credentials for the Odoo layer
url = os.getenv('ODOO_URL', 'http://localhost:8069')
db = os.getenv('ODOO_DB') # This must be 'my_dev_db'
username = os.getenv('ODOO_ADMIN_USER', 'admin')
password = os.getenv('ODOO_ADMIN_PASSWORD', 'admin')

# --- 1. INITIAL HANDSHAKE (Common Endpoint) ---
try:
    common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
    
    # Authenticate and get the User ID (uid)
    uid = common.authenticate(db, username, password, {})
    
    if not uid:
        print(f"❌ Login Failed: Check if password for '{username}' is correct in .env")
        exit()
        
    print(f"✅ Connected to Odoo! UID: {uid}")

except xmlrpc.client.Fault as e:
    if "KeyError: 'res.users'" in str(e):
        print(f"❌ Error: The database '{db}' was not found on the server.")
        print("💡 Tip: Ensure ODOO_DB in your .env matches the database name in your browser.")
    else:
        print(f"❌ Odoo Server Error: {e}")
    exit()
except Exception as e:
    print(f"💥 Connection Error: {e}")
    exit()

# --- 2. DATA INTERACTION (Object Endpoint) ---
# This is where we actually talk to the models (tables)
models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')

# --- 3. SEARCH (Find IDs) ---
# We want partners that are companies. Note: Domain is a list of tuples.
domain = [('is_company', '=', True)]

# execute_kw(db, uid, password, model, method, [args])
ids = models.execute_kw(db, uid, password, 'res.partner', 'search', [domain])

# --- 4. READ (Get Data) ---
if ids:
    # We pass the list of IDs and a dictionary of the fields we want back
    params = {'fields': ['name', 'email', 'city']}
    records = models.execute_kw(db, uid, password, 'res.partner', 'read', [ids], params)

    print(f"\n📊 Found {len(records)} Company Records:")
    print("-" * 40)
    for record in records:
        name = record.get('name')
        # Odoo returns False for empty fields, so we use 'or' for clean printing
        email = record.get('email') or "No Email"
        city = record.get('city') or "No City"
        print(f"🏢 {name: <20} | 📧 {email: <20} | 📍 {city}")
else:
    print("Empty database. No companies found.")