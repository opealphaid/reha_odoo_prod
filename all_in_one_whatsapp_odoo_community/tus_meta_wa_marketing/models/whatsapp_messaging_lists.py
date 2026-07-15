from odoo import fields, models


class WhatsAppMessagingLists(models.Model):
    _description = "Whatsapp Messaging Lists"
    _name = "whatsapp.messaging.lists"
    _rec_name = "name"

    name = fields.Char("Name")
    contact_type = fields.Selection(
        [("base_contact", "Contacts"), ("wa_list_contact", "WA List Contacts")],
        string="Contact Type",
        default="base_contact",
    )
    wa_list_contacts_ids = fields.Many2many(
        "whatsapp.messaging.lists.contacts", string="Message List Contacts"
    )
    contact_ids = fields.Many2many("res.partner", string="Contacts")
