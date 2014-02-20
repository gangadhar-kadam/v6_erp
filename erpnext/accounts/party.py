# Copyright (c) 2013, Web Notes Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.defaults import get_restrictions
from frappe.utils import add_days
from erpnext.utilities.doctype.address.address import get_address_display
from erpnext.utilities.doctype.contact.contact import get_contact_details

@frappe.whitelist()
def get_party_details(party=None, account=None, party_type="Customer", company=None, 
	posting_date=None, price_list=None, currency=None):

	return _get_party_details(party, account, party_type, company, posting_date, price_list, currency)

def _get_party_details(party=None, account=None, party_type="Customer", company=None, 
	posting_date=None, price_list=None, currency=None, ignore_permissions=False):
	out = frappe._dict(set_account_and_due_date(party, account, party_type, company, posting_date))
	
	party = out[party_type.lower()]

	if not ignore_permissions and not frappe.has_permission(party_type, "read", party):
		frappe.throw("Not Permitted", frappe.PermissionError)

	party_bean = frappe.bean(party_type, party)
	party = party_bean.doc

	set_address_details(out, party, party_type)
	set_contact_details(out, party, party_type)
	set_other_values(out, party, party_type)
	set_price_list(out, party, price_list)
	
	if not out.get("currency"):
		out["currency"] = currency
	
	# sales team
	if party_type=="Customer":
		out["sales_team"] = [{
			"sales_person": d.sales_person, 
			"sales_designation": d.sales_designation
		} for d in party_bean.doclist.get({"doctype":"Sales Team"})]
	
	return out

def set_address_details(out, party, party_type):
	billing_address_field = "customer_address" if party_type == "Lead" \
		else party_type.lower() + "_address"
	out[billing_address_field] = frappe.conn.get_value("Address", 
		{party_type.lower(): party.name, "is_primary_address":1}, "name")
	
	# address display
	out.address_display = get_address_display(out[billing_address_field])
	
	# shipping address
	if party_type in ["Customer", "Lead"]:
		out.shipping_address_name = frappe.conn.get_value("Address", 
			{party_type.lower(): party.name, "is_shipping_address":1}, "name")
		out.shipping_address = get_address_display(out["shipping_address_name"])
	
def set_contact_details(out, party, party_type):
	out.contact_person = frappe.conn.get_value("Contact", 
		{party_type.lower(): party.name, "is_primary_contact":1}, "name")
	
	out.update(get_contact_details(out.contact_person))

def set_other_values(out, party, party_type):
	# copy
	if party_type=="Customer":
		to_copy = ["customer_name", "customer_group", "territory"]
	else:
		to_copy = ["supplier_name", "supplier_type"]
	for f in to_copy:
		out[f] = party.get(f)
	
	# fields prepended with default in Customer doctype
	for f in ['currency', 'taxes_and_charges'] \
		+ (['sales_partner', 'commission_rate'] if party_type=="Customer" else []):
		if party.get("default_" + f):
			out[f] = party.get("default_" + f)

def set_price_list(out, party, given_price_list):
	# price list	
	price_list = get_restrictions().get("Price List")
	if isinstance(price_list, list):
		price_list = None

	if not price_list:
		price_list = party.default_price_list
		
	if not price_list and party.party_type=="Customer":
		price_list =  frappe.conn.get_value("Customer Group", 
			party.customer_group, "default_price_list")

	if not price_list:
		price_list = given_price_list

	if price_list:
		out.price_list_currency = frappe.conn.get_value("Price List", price_list, "currency")
		
	out["selling_price_list" if party.doctype=="Customer" else "buying_price_list"] = price_list
	

def set_account_and_due_date(party, account, party_type, company, posting_date):
	if not posting_date:
		# not an invoice
		return {
			party_type.lower(): party
		}
	
	if party:
		account = get_party_account(company, party, party_type)
	elif account:
		party = frappe.conn.get_value('Account', account, 'master_name')

	account_fieldname = "debit_to" if party_type=="Customer" else "credit_to" 

	out = {
		party_type.lower(): party,
		account_fieldname : account,
		"due_date": get_due_date(posting_date, party, party_type, account, company)
	}
	return out

def get_party_account(company, party, party_type):
	if not company:
		frappe.throw(_("Please select company first."))

	if party:
		acc_head = frappe.conn.get_value("Account", {"master_name":party,
			"master_type": party_type, "company": company})

		if not acc_head:
			create_party_account(party, party_type, company)
	
		return acc_head		

def get_due_date(posting_date, party, party_type, account, company):
	"""Set Due Date = Posting Date + Credit Days"""
	due_date = None
	if posting_date:
		credit_days = 0
		if account:
			credit_days = frappe.conn.get_value("Account", account, "credit_days")
		if party and not credit_days:
			credit_days = frappe.conn.get_value(party_type, party, "credit_days")
		if company and not credit_days:
			credit_days = frappe.conn.get_value("Company", company, "credit_days")
			
		due_date = add_days(posting_date, credit_days) if credit_days else posting_date

	return due_date	

def create_party_account(party, party_type, company):
	if not company:
		frappe.throw(_("Company is required"))
		
	company_details = frappe.conn.get_value("Company", company, 
		["abbr", "receivables_group", "payables_group"], as_dict=True)
	if not frappe.conn.exists("Account", (party + " - " + company_details.abbr)):
		parent_account = company_details.receivables_group \
			if party_type=="Customer" else company_details.payables_group

		# create
		account = frappe.bean({
			"doctype": "Account",
			'account_name': party,
			'parent_account': parent_account, 
			'group_or_ledger':'Ledger',
			'company': company, 
			'master_type': party_type, 
			'master_name': party,
			"freeze_account": "No"
		}).insert(ignore_permissions=True)
		
		frappe.msgprint(_("Account Created") + ": " + account.doc.name)
