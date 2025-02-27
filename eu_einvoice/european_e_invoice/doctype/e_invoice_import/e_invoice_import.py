# Copyright (c) 2024, ALYF GmbH and contributors
# For license information, please see license.txt


from pathlib import Path
from typing import TYPE_CHECKING

import frappe
from drafthorse.models.document import Document as DrafthorseDocument
from erpnext import get_default_company
from erpnext.edi.doctype.code_list.code_list import get_docnames_for
from facturx import get_xml_from_pdf
from frappe import _, _dict, get_site_path
from frappe.model.document import Document
from frappe.model.mapper import get_mapped_doc

from eu_einvoice.schematron import Stylesheet, get_validation_errors
from eu_einvoice.utils import format_heading

if TYPE_CHECKING:
	from drafthorse.models.accounting import ApplicableTradeTax
	from drafthorse.models.party import PostalTradeAddress, TradeParty
	from drafthorse.models.payment import PaymentTerms
	from drafthorse.models.tradelines import LineItem
	from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import PurchaseInvoice


class EInvoiceImport(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from eu_einvoice.european_e_invoice.doctype.e_invoice_item.e_invoice_item import EInvoiceItem
		from eu_einvoice.european_e_invoice.doctype.e_invoice_payment_term.e_invoice_payment_term import (
			EInvoicePaymentTerm,
		)
		from eu_einvoice.european_e_invoice.doctype.e_invoice_trade_tax.e_invoice_trade_tax import (
			EInvoiceTradeTax,
		)

		amended_from: DF.Link | None
		buyer_address_line_1: DF.Data | None
		buyer_address_line_2: DF.Data | None
		buyer_city: DF.Data | None
		buyer_country: DF.Link | None
		buyer_name: DF.Data | None
		buyer_postcode: DF.Data | None
		company: DF.Link | None
		correct_european_invoice: DF.Check
		correct_german_federal_administration_invoice: DF.Check
		currency: DF.Link | None
		due_date: DF.Date | None
		einvoice: DF.Attach | None
		id: DF.Data | None
		issue_date: DF.Date | None
		items: DF.Table[EInvoiceItem]
		payment_terms: DF.Table[EInvoicePaymentTerm]
		purchase_order: DF.Link | None
		seller_address_line_1: DF.Data | None
		seller_address_line_2: DF.Data | None
		seller_city: DF.Data | None
		seller_country: DF.Link | None
		seller_name: DF.Data | None
		seller_postcode: DF.Data | None
		seller_tax_id: DF.Data | None
		supplier: DF.Link | None
		supplier_address: DF.Link | None
		taxes: DF.Table[EInvoiceTradeTax]
		validation_errors: DF.Text | None
	# end: auto-generated types

	def validate(self):
		if (
			self.id
			and self.supplier
			and frappe.db.get_single_value("Accounts Settings", "check_supplier_invoice_uniqueness")
			and frappe.db.exists(
				"E Invoice Import", {"id": self.id, "name": ("!=", self.name), "supplier": self.supplier}
			)
		):
			frappe.throw(_("An E Invoice Import with the same Invoice ID and Supplier already exists."))

	def before_save(self):
		if self.einvoice and self.has_value_changed("einvoice"):
			self.read_values_from_einvoice()
			self.guess_supplier()
			self.guess_company()
			self.guess_uom()

	def before_submit(self):
		if not self.supplier:
			frappe.throw(_("Please create or select a supplier before submitting"))

		if not self.company:
			frappe.throw(_("Please select a company before submitting"))

		if not (self.items and all(row.item for row in self.items)):
			frappe.throw(_("Please map all invoice lines to an item before submitting"))

	def on_submit(self):
		self.add_seller_product_ids_to_items()

	def onload(self):
		if self.docstatus == 0:
			return

		invoices = frappe.get_list(
			"Purchase Invoice",
			filters={"bill_no": self.id, "supplier": self.supplier, "company": self.company},
			fields=["name", "e_invoice_import"],
		)
		linked_invoice = next(
			(invoice.name for invoice in invoices if invoice.e_invoice_import == self.name), None
		)
		unlinked_invoice = next((invoice.name for invoice in invoices if not invoice.e_invoice_import), None)

		self.set_onload("linked_invoice", linked_invoice)
		self.set_onload("unlinked_invoice", unlinked_invoice)

	def get_xml_bytes(self) -> bytes:
		return get_xml_bytes(Path(get_site_path(self.einvoice.lstrip("/"))).resolve())

	def read_values_from_einvoice(self) -> None:
		xml_bytes = self.get_xml_bytes()
		doc = DrafthorseDocument.parse(xml_bytes)

		self._validate_schematron(xml_bytes)

		self.id = str(doc.header.id)
		self.issue_date = str(doc.header.issue_date_time)
		self.currency = str(doc.trade.settlement.currency_code)
		self.parse_seller(doc.trade.agreement.seller)
		self.parse_buyer(doc.trade.agreement.buyer)

		buyer_reference = str(doc.trade.agreement.buyer_order.issuer_assigned_id)
		if (
			not self.purchase_order
			and buyer_reference
			and frappe.db.exists("Purchase Order", buyer_reference)
		):
			self.purchase_order = buyer_reference

		self.items = []
		for li in doc.trade.items.children:
			self.parse_line_item(li)

		self.taxes = []
		for tax in doc.trade.settlement.trade_tax.children:
			self.parse_tax(tax)

		self.payment_terms = []
		for term in doc.trade.settlement.terms.children:
			self.parse_payment_term(term)

	def _validate_schematron(self, xml_bytes):
		self.validation_errors = ""
		xml_string = xml_bytes.decode("utf-8")

		try:
			en_validation_errors = get_validation_errors(xml_string, Stylesheet.EN16931)
			xr_validation_errors = get_validation_errors(xml_string, Stylesheet.XRECHNUNG)
		except Exception:
			frappe.log_error(
				title="E Invoice schematron validation",
				reference_doctype=self.doctype,
				reference_name=self.name,
			)
			frappe.msgprint(
				_("Could not validate E Invoice schematron. See Error Log for details."),
				alert=True,
				indicator="orange",
			)
			return

		if any(en_validation_errors):
			self.correct_european_invoice = 0
			self.validation_errors += format_heading(_("European Invoice")) + "\n".join(en_validation_errors)
		else:
			self.correct_european_invoice = 1

		if any(xr_validation_errors):
			self.correct_german_federal_administration_invoice = 0
			if self.validation_errors:
				self.validation_errors += "\n"
			self.validation_errors += format_heading(_("German Federal Administration Invoice")) + "\n".join(
				xr_validation_errors
			)
		else:
			self.correct_german_federal_administration_invoice = 1

	def parse_seller(self, seller: "TradeParty"):
		self.seller_name = str(seller.name)
		self.seller_tax_id = (
			seller.tax_registrations.children[0].id._text if seller.tax_registrations.children else None
		)
		self.parse_address(seller.address, "seller")

	def parse_buyer(self, buyer: "TradeParty"):
		self.buyer_name = str(buyer.name)
		self.parse_address(buyer.address, "buyer")

	def parse_address(self, address: "PostalTradeAddress", prefix: str) -> _dict:
		country = frappe.db.get_value("Country", {"code": str(address.country_id).lower()}, "name")

		self.set(f"{prefix}_city", str(address.city_name))
		self.set(f"{prefix}_address_line_1", str(address.line_one))
		self.set(f"{prefix}_address_line_2", str(address.line_two))
		self.set(f"{prefix}_postcode", str(address.postcode))
		self.set(f"{prefix}_country", str(country))

	def parse_line_item(self, li: "LineItem"):
		item = self.append("items")
		supplier = None

		net_rate = float(li.agreement.net.amount._value)
		basis_qty = float(li.agreement.net.basis_quantity._amount or "1")
		rate = net_rate / basis_qty

		item.product_name = str(li.product.name)
		item.product_description = str(li.product.description)
		item.seller_product_id = str(li.product.seller_assigned_id)
		item_code = str(li.product.buyer_assigned_id)
		if item_code and not frappe.db.exists("Item", item_code):
			item_code = None

		if item.seller_product_id and supplier and not item_code:
			item_code = frappe.db.get_value(
				"Item Supplier", {"supplier": supplier, "supplier_part_no": item.seller_product_id}, "parent"
			)
		item.item = item_code or None

		item.billed_quantity = flt_or_none(li.delivery.billed_quantity._amount)
		item.unit_code = str(li.delivery.billed_quantity._unit_code)
		item.net_rate = rate
		item.tax_rate = flt_or_none(li.settlement.trade_tax.rate_applicable_percent._value)
		item.total_amount = flt_or_none(li.settlement.monetary_summation.total_amount._value)

	def parse_tax(self, tax: "ApplicableTradeTax"):
		t = self.append("taxes")
		t.basis_amount = flt_or_none(tax.basis_amount._value)
		t.rate_applicable_percent = flt_or_none(tax.rate_applicable_percent._value)
		t.calculated_amount = flt_or_none(tax.calculated_amount._value)

	def parse_payment_term(self, term: "PaymentTerms"):
		if not term.partial_amount.children:
			self.due_date = term.due._value
			return

		t = self.append("payment_terms")
		t.due = term.due._value
		partial_amount = None
		for row in term.partial_amount.children:
			if isinstance(row, tuple):
				# row = (amount, currency)
				if row[1] == self.currency:
					partial_amount = row[0]
					break
			else:
				# row = amount
				partial_amount = row
				break

		t.partial_amount = float(partial_amount) if partial_amount is not None else None
		t.description = term.description
		t.discount_basis_date = term.discount_terms.basis_date_time._value

		if term.discount_terms.calculation_percent._value:
			t.discount_calculation_percent = float(term.discount_terms.calculation_percent._value)

		if term.discount_terms.actual_amount._value:
			t.discount_actual_amount = float(term.discount_terms.actual_amount._value)

	def guess_supplier(self):
		if self.supplier:
			return

		if frappe.db.exists("Supplier", self.seller_name):
			self.supplier = self.seller_name

		if self.seller_tax_id:
			self.supplier = frappe.db.get_value("Supplier", {"tax_id": self.seller_tax_id}, "name")

	def guess_company(self):
		if self.company:
			return

		if frappe.db.exists("Company", self.buyer_name):
			self.company = self.buyer_name
		else:
			self.company = get_default_company()

	def guess_uom(self):
		for row in self.items:
			if row.uom:
				continue

			if row.unit_code:
				rec20_3 = get_docnames_for("urn:xoev-de:kosit:codeliste:rec20_3", "UOM", row.unit_code)
				if rec20_3:
					row.uom = rec20_3[0]
				else:
					rec21_3 = get_docnames_for("urn:xoev-de:kosit:codeliste:rec21_3", "UOM", row.unit_code)
					if rec21_3:
						row.uom = rec21_3[0]
			elif row.item:
				stock_uom, purchase_uom = frappe.db.get_value("Item", row.item, ["stock_uom", "purchase_uom"])
				row.uom = purchase_uom or stock_uom

	def add_seller_product_ids_to_items(self):
		for row in self.items:
			try:
				# This is a convenience feature. Failure to update the Item data
				# should not prevent submission of the E Invoice Import.
				row.add_seller_product_id_to_item(self.supplier)
			except frappe.ValidationError:
				frappe.log_error(
					title="Failed to store Seller Product ID",
					reference_doctype=self.doctype,
					reference_name=self.name,
				)


def flt_or_none(value) -> float | None:
	return float(value) if value is not None else None


def get_xml_bytes(file: Path) -> bytes:
	"""Reads the XML data from the given XML or PDF file path."""
	if file.suffix == ".pdf":
		xml_filename, xml_bytes = get_xml_from_pdf(file.read_bytes(), check_xsd=False)
		if not xml_bytes:
			frappe.throw(_("No XML data found in PDF file."))
	elif file.suffix == ".xml":
		xml_bytes = file.read_bytes()
	else:
		frappe.throw(_("Unsupported file format '{0}'").format(file.suffix))

	return xml_bytes


@frappe.whitelist()
def create_purchase_invoice(source_name, target_doc=None):
	def post_process(source, target: "PurchaseInvoice"):
		target.set_missing_values()

	def process_tax_row(source, target, source_parent) -> None:
		target.charge_type = "Actual"

	def process_payment_term(source, target, source_parent):
		if source.discount_calculation_percent:
			target.discount_type = "Percentage"
			target.discount = source.discount_calculation_percent
		elif source.discount_actual_amount:
			target.discount_type = "Amount"
			target.discount = source.discount_actual_amount

	return get_mapped_doc(
		"E Invoice Import",
		source_name,
		{
			"E Invoice Import": {
				"doctype": "Purchase Invoice",
				"field_map": {
					"name": "e_invoice_import",
					"supplier": "supplier",
					"company": "company",
					"id": "bill_no",
					"issue_date": "bill_date",
					"currency": "currency",
				},
				# "field_no_map": ["items"],
			},
			"E Invoice Item": {
				"doctype": "Purchase Invoice Item",
				"field_map": {
					"item": "item_code",
					"billed_quantity": "qty",
					"uom": "uom",
					"net_rate": "rate",
				},
			},
			"E Invoice Trade Tax": {
				"doctype": "Purchase Taxes and Charges",
				"field_map": {
					"tax_account": "account_head",
					"rate_applicable_percent": "rate",
					"calculated_amount": "tax_amount",
				},
				"postprocess": process_tax_row,
			},
			"E Invoice Payment Term": {
				"doctype": "Payment Schedule",
				"field_map": {
					"due": "due_date",
					"partial_amount": "payment_amount",
					"description": "description",
					"discount_basis_date": "discount_date",
				},
				"postprocess": process_payment_term,
			},
		},
		target_doc,
		post_process,
	)


@frappe.whitelist()
def create_supplier(source_name, target_doc=None):
	return get_mapped_doc(
		"E Invoice Import",
		source_name,
		{
			"E Invoice Import": {
				"doctype": "Supplier",
				"field_map": {
					"seller_name": "supplier_name",
					"seller_tax_id": "tax_id",
					"seller_country": "country",
					"currency": "default_currency",
				},
			}
		},
		target_doc,
	)


@frappe.whitelist()
def create_supplier_address(source_name, target_doc=None):
	def post_process(source, target):
		target.append("links", {"link_doctype": "Supplier", "link_name": source.supplier})

	return get_mapped_doc(
		"E Invoice Import",
		source_name,
		{
			"E Invoice Import": {
				"doctype": "Address",
				"field_map": {
					"seller_address_line_1": "address_line1",
					"seller_address_line_2": "address_line2",
					"seller_city": "city",
					"seller_postcode": "pincode",
					"seller_country": "country",
				},
			}
		},
		target_doc,
		post_process,
	)


@frappe.whitelist()
def create_item(source_name, target_doc=None):
	def post_process(source, target):
		if frappe.db.get_single_value("Stock Settings", "item_naming_by") == "Item Code":
			target.item_code = target.item_name
		target.is_purchase_item = 1
		target.append(
			"supplier_items",
			{
				"supplier": frappe.db.get_value("E Invoice Import", source.parent, "supplier"),
				"supplier_part_no": source.seller_product_id,
			},
		)

	return get_mapped_doc(
		"E Invoice Item",
		source_name,
		{
			"E Invoice Item": {
				"doctype": "Item",
				"field_map": {
					"product_name": "item_name",
					"product_description": "description",
					"uom": "stock_uom",
				},
			}
		},
		target_doc,
		post_process,
	)


@frappe.whitelist()
def create_einvoice_from_po(source_name, target_doc=None):
	return get_mapped_doc(
		"Purchase Order",
		source_name,
		{
			"Purchase Order": {
				"doctype": "E Invoice Import",
				"field_map": {
					"name": "purchase_order",
				},
				"field_no_map": ["items"],
			}
		},
		target_doc,
	)


@frappe.whitelist()
def link_to_purchase_invoice(einvoice: str, purchase_invoice: str):
	"""Link an existing E Invoice Import to an existing Purchase Invoice."""
	pi = frappe.get_doc("Purchase Invoice", purchase_invoice)
	pi.check_permission("write")
	if pi.e_invoice_import:
		frappe.throw(
			_("Purchase Invoice {0} is already linked to E Invoice Import {1}").format(
				purchase_invoice, pi.e_invoice_import
			)
		)

	if not frappe.db.get_list("E Invoice Import", filters={"name": einvoice}, limit=1):
		frappe.throw(_("E Invoice Import {0} does not exist").format(einvoice))

	pi.db_set("e_invoice_import", einvoice)
