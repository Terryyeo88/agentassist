#!/bin/bash
# SAP B1 Service Layer Connection Test Script
# Run this BEFORE attempting MCP server setup
# Usage: ./test-service-layer.sh <IP> <PASSWORD>

IP=${1:?"Usage: ./test-service-layer.sh <IP> <PASSWORD>"}
PASSWORD=${2:?"Usage: ./test-service-layer.sh <IP> <PASSWORD>"}
DB="SBODEMOSG"
USER="manager"
BASE="https://${IP}:50000/b1s/v2"

echo "============================================"
echo "SAP B1 Service Layer Connection Test"
echo "Target: ${BASE}"
echo "Database: ${DB}"
echo "============================================"
echo ""

# Test 1: Login
echo "--- TEST 1: Login ---"
LOGIN_RESPONSE=$(curl -sk -X POST \
  "${BASE}/Login" \
  -H "Content-Type: application/json" \
  -d "{\"CompanyDB\":\"${DB}\",\"UserName\":\"${USER}\",\"Password\":\"${PASSWORD}\"}" \
  -c /tmp/b1cookies.txt \
  -w "\nHTTP_STATUS:%{http_code}")

HTTP_STATUS=$(echo "$LOGIN_RESPONSE" | grep "HTTP_STATUS" | cut -d: -f2)
BODY=$(echo "$LOGIN_RESPONSE" | grep -v "HTTP_STATUS")

if [ "$HTTP_STATUS" = "200" ]; then
  echo "✅ Login successful (HTTP 200)"
  echo "Response: ${BODY}"
else
  echo "❌ Login FAILED (HTTP ${HTTP_STATUS})"
  echo "Response: ${BODY}"
  echo ""
  echo "Troubleshooting:"
  echo "  - Check IP address and port 50000 is reachable"
  echo "  - Check GCP firewall rule for port 50000"
  echo "  - Check company database name (case-sensitive)"
  echo "  - Check password"
  exit 1
fi
echo ""

# Test 2: Read Business Partners
echo "--- TEST 2: Read Business Partners ---"
BP_RESPONSE=$(curl -sk -X GET \
  "${BASE}/BusinessPartners?\$top=3&\$select=CardCode,CardName,CardType" \
  -b /tmp/b1cookies.txt \
  -w "\nHTTP_STATUS:%{http_code}")

HTTP_STATUS=$(echo "$BP_RESPONSE" | grep "HTTP_STATUS" | cut -d: -f2)
BODY=$(echo "$BP_RESPONSE" | grep -v "HTTP_STATUS")

if [ "$HTTP_STATUS" = "200" ]; then
  echo "✅ Business Partners retrieved (HTTP 200)"
  echo "Response (first 500 chars): ${BODY:0:500}"
else
  echo "❌ Business Partners FAILED (HTTP ${HTTP_STATUS})"
  echo "Response: ${BODY}"
fi
echo ""

# Test 3: Read Tax Codes (Singapore-specific)
echo "--- TEST 3: Read Sales Tax Codes ---"
TAX_RESPONSE=$(curl -sk -X GET \
  "${BASE}/SalesTaxCodes?\$select=Code,Name,Rate" \
  -b /tmp/b1cookies.txt \
  -w "\nHTTP_STATUS:%{http_code}")

HTTP_STATUS=$(echo "$TAX_RESPONSE" | grep "HTTP_STATUS" | cut -d: -f2)
BODY=$(echo "$TAX_RESPONSE" | grep -v "HTTP_STATUS")

if [ "$HTTP_STATUS" = "200" ]; then
  echo "✅ Tax Codes retrieved (HTTP 200)"
  echo "Response (first 500 chars): ${BODY:0:500}"
  
  # Check for Singapore-specific codes
  if echo "$BODY" | grep -q '"SR"'; then
    echo "✅ Found SR (Standard Rated) — Singapore localisation confirmed!"
  else
    echo "⚠️  SR tax code not found — may not be Singapore localisation"
  fi
else
  echo "❌ Tax Codes FAILED (HTTP ${HTTP_STATUS})"
  echo "Response: ${BODY}"
fi
echo ""

# Test 4: Read Chart of Accounts
echo "--- TEST 4: Read Chart of Accounts ---"
COA_RESPONSE=$(curl -sk -X GET \
  "${BASE}/ChartOfAccounts?\$top=5&\$select=Code,Name,AccountType" \
  -b /tmp/b1cookies.txt \
  -w "\nHTTP_STATUS:%{http_code}")

HTTP_STATUS=$(echo "$COA_RESPONSE" | grep "HTTP_STATUS" | cut -d: -f2)
BODY=$(echo "$COA_RESPONSE" | grep -v "HTTP_STATUS")

if [ "$HTTP_STATUS" = "200" ]; then
  echo "✅ Chart of Accounts retrieved (HTTP 200)"
  echo "Response (first 500 chars): ${BODY:0:500}"
else
  echo "❌ Chart of Accounts FAILED (HTTP ${HTTP_STATUS})"
  echo "Response: ${BODY}"
fi
echo ""

# Test 5: Logout
echo "--- TEST 5: Logout ---"
curl -sk -X POST "${BASE}/Logout" -b /tmp/b1cookies.txt -w "HTTP_STATUS:%{http_code}\n"
echo ""

# Cleanup
rm -f /tmp/b1cookies.txt

echo "============================================"
echo "Test complete. If all tests show ✅, proceed"
echo "to MCP server setup."
echo "============================================"
