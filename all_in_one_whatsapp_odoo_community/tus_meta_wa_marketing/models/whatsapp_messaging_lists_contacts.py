from odoo import fields, models, api, _
from odoo.exceptions import ValidationError


class WhatsAppMessagingListsContacts(models.Model):
    _description = "Whatsapp Messaging List Contacts"
    _name = "whatsapp.messaging.lists.contacts"
    _rec_name = "phone"

    name = fields.Char("Contact Name")
    phone = fields.Char("WhatsApp Number")
    created_date = fields.Date(string='Create Date', default=fields.Date.context_today)

    @api.constrains('phone')
    def _verify_phone_number(self):
        for rec in self:
            if rec.phone and not rec.phone.isdigit():
                raise ValidationError(_("The Phone Number must be a sequence of digits."))
