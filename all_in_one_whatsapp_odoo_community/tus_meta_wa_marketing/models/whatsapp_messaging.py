import json
import logging
from datetime import datetime
from odoo import api, fields, models, tools, _
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval
from odoo.tools.misc import split_every
from odoo.addons.all_in_one_whatsapp_odoo_community.tus_meta_whatsapp_base.models.whatsapp_history import image_type, video_type, audio_type, document_type

_logger = logging.getLogger(__name__)

MASS_WHATSAPP_BUSINESS_MODELS = ["res.partner", "whatsapp.messaging.lists"]


class WhatsAppMessaging(models.Model):
    _description = "Whatsapp Messaging"
    _name = "whatsapp.messaging"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _rec_name = "name"

    def _get_current_model_template(self):
        domain = [("model", "in", ["res.partner", "whatsapp.messaging.lists"]),
                  ("state", "=", "added")]
        provider_id = self.user_id.provider_ids.filtered(lambda x: x.company_id in self.company_ids)
        provider_id and domain.append(("provider_id", "=", fields.first(provider_id).id)) or domain.append(("create_uid", "=", self.env.user.id))
        return domain

    name = fields.Char("Name", required=True)

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("in_queue", "In Queue"),
            ("sending", "Sending"),
            ("done", "Sent"),
        ],
        string="Status",
        required=True,
        copy=False,
        default="draft",
    )
    domain = fields.Boolean("Domain")
    partner_ids = fields.Many2many("res.partner", string="Partners")
    whatsapp_messaging_lists_ids = fields.Many2many("whatsapp.messaging.lists")
    wa_messaging_model_id = fields.Many2one(
        "ir.model",
        string="Recipients Model",
        domain=[("model", "in", MASS_WHATSAPP_BUSINESS_MODELS)],
    )
    wa_messaging_domain = fields.Char(string="WA Messaging Domain", default=[])
    body_html = fields.Html("Body", translate=True, sanitize=False)
    schedule_date = fields.Datetime(string="Schedule in the Future")
    company_ids = fields.Many2many(
        "res.company", string="Company", default=lambda self: self.env.companies
    )
    user_id = fields.Many2one(
        "res.users", string="User", default=lambda self: self.env.user
    )

    template_id = fields.Many2one(
        "wa.template",
        "Use template",
        index=True,
        domain=_get_current_model_template,
    )
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "whatsapp_messaging_ir_attachments_rel",
        "whatsapp_messaging_id",
        "attachment_id",
        "Attachments",
    )
    is_partner = fields.Boolean(string="Partner", compute="_compute_partner")
    mail_history_ids = fields.One2many("whatsapp.history", "whatsapp_messaging_id")
    marketing_contact_mes_history_ids = fields.One2many(
        "marketing.contact.history", "marketing_contact_id"
    )

    provider_id = fields.Many2one("provider", "Provider")
    allowed_provider_ids = fields.Many2many(
        "provider", "Provider", compute="update_allowed_providers"
    )
    received_ratio = fields.Integer(
        compute="_compute_statistics", string="Received Ratio"
    )
    inqueue_ratio = fields.Integer(compute="_compute_statistics", string="In Queue Ratio")
    sent_ratio = fields.Integer(compute="_compute_statistics", string="Sent Ratio")
    delivered_ratio = fields.Integer(compute="_compute_statistics", string="Delivered Ratio")
    read_ratio = fields.Integer(compute="_compute_statistics", string="Read Ratio")
    fail_ratio = fields.Integer(compute="_compute_statistics", string="Fail Ratio")
    is_cron_run = fields.Boolean(string="Is Marketing Executed", copy=False)

    def _compute_statistics(self):
        for rec in self:
            query = 'select type,count(*) AS count from whatsapp_history  where whatsapp_messaging_id =%d group by type ;' % rec.id
            self.env.cr.execute(query)
            types = self._cr.fetchall()
            received = inqueue = sent = delivered = read = fail = 0
            for val in types:
                if val[0] == 'in queue':
                    inqueue += val[1]
                elif val[0] == 'received':
                    received += val[1]
                elif val[0] == 'delivered':
                    delivered += val[1]
                elif val[0] == 'read':
                    read += val[1]
                elif val[0] == 'sent':
                    sent += val[1]
                else:
                    fail += val[1]

            total_wa_history = received + inqueue + sent + delivered + read + fail
            rec.received_ratio = (received / total_wa_history) * 100 if total_wa_history != 0 else 0
            rec.inqueue_ratio = (inqueue / total_wa_history) * 100 if total_wa_history != 0 else 0
            rec.sent_ratio = (sent / total_wa_history) * 100 if total_wa_history != 0 else 0
            rec.delivered_ratio = (delivered / total_wa_history) * 100 if total_wa_history != 0 else 0
            rec.read_ratio = (read / total_wa_history) * 100 if total_wa_history != 0 else 0
            rec.fail_ratio = (fail / total_wa_history) * 100 if total_wa_history != 0 else 0

    def action_view_documents_filtered(self):
        action = self.env["ir.actions.actions"]._for_xml_id(
            "all_in_one_whatsapp_odoo_community.whatsapp_history_action"
        )
        view_filter = self._context.get('state', '')
        action["domain"] = [
            ("type", "=", view_filter),
            ("whatsapp_messaging_id", "=", self.id),
        ]
        return action

    @api.depends("company_ids")
    def update_allowed_providers(self):
        self.allowed_provider_ids = self.env.user.provider_ids

    @api.onchange("company_ids", "provider_id")
    def onchange_company_provider(self):
        self.template_id = False
        return {
            "domain": {
                "template_id": [
                    ("model_id.model", "=", "res.partner"),
                    ("provider_id", "=", self.provider_id.id),
                ]
            }
        }

    @api.depends("wa_messaging_model_id")
    def _compute_partner(self):
        # simple logic, but you can do much more here
        for rec in self:
            if rec.wa_messaging_model_id.model == "res.partner":
                rec.is_partner = True
            else:
                rec.is_partner = False

    def action_schedule_date(self):
        self.ensure_one()
        action = self.env.ref(
            "all_in_one_whatsapp_odoo_community.whatsapp_messaging_schedule_date_action"
        ).read()[0]
        action["context"] = dict(
            self.env.context, default_whatsapp_messaging_id=self.id
        )
        return action

    def put_in_queue(self):
        self.write({"state": "in_queue"})

    def cancel_mass_mailing(self):
        self.write({"state": "draft", "schedule_date": False})

    def action_test_whatsapp_marketing(self):
        for record in self:
            return {
                'name': 'Test Whatsapp Marketing',
                'type': 'ir.actions.act_window',
                'view_mode': 'form',
                "view_type": "form",
                'res_model': 'test.whatsapp.marketing',
                'target': 'new',
                'view_id': self.env.ref('all_in_one_whatsapp_odoo_community.test_whatsapp_marketing_wizard_form').id,
                'context': {'default_template_id': record.template_id.id,
                            'default_body_html': record.template_id.body_html},
            }

    @api.onchange("template_id", 'whatsapp_messaging_lists_ids')
    def onchange_template_id_wrapper(self):
        self.ensure_one()
        if self.template_id:
            user_error = False
            if self.template_id.components_ids and self.wa_messaging_model_id.model == "whatsapp.messaging.lists":
                if self.whatsapp_messaging_lists_ids.contact_ids and self.whatsapp_messaging_lists_ids.filtered(
                        lambda x: x.contact_type == 'base_contact') and self.whatsapp_messaging_lists_ids.wa_list_contacts_ids and self.whatsapp_messaging_lists_ids.filtered(
                    lambda x: x.contact_type == 'wa_list_contact'):
                    raise UserError(_('You Can not select Contact list and Marketing message list at the same time'))
                user_error = bool(self.template_id.components_ids.mapped('variables_ids'))
            if self.whatsapp_messaging_lists_ids.wa_list_contacts_ids and self.whatsapp_messaging_lists_ids.filtered(lambda x: x.contact_type == 'wa_list_contact'):
                if user_error:
                    raise UserError(("You cannot select the template with dynamic value. please select another one!"))
            self.body_html = self.template_id._render_field(
                "body_html",
                [self.env.user.partner_id.id],
                compute_lang=True,
            )[self.env.user.partner_id.id]
        else:
            self.body_html = ""

    @api.model
    def _process_whatsapp_messaging_queue(self):
        whatsapp_messagings = self.search([
            ("state", "in", ("in_queue", "sending")), "|", ("schedule_date", "<", fields.Datetime.now()),
            ("schedule_date", "=", False), ("is_cron_run", '=', False)])
        for whatsapp_messaging in whatsapp_messagings:
            try:
                sequence = 1
                user = whatsapp_messaging.user_id
                message_partner = 0
                unique_phones = set()
                if whatsapp_messaging.is_partner or whatsapp_messaging.whatsapp_messaging_lists_ids.filtered(lambda x: x.contact_type == 'base_contact') and whatsapp_messaging.whatsapp_messaging_lists_ids.contact_ids:
                    to_partners = whatsapp_messaging.whatsapp_messaging_lists_ids.mapped('contact_ids').filtered(lambda x: x.mobile and (x.mobile not in unique_phones and not unique_phones.add(x.mobile)))
                    to_partners |= whatsapp_messaging.partner_ids.filtered(lambda x: x.mobile and (x.mobile not in unique_phones and not unique_phones.add(x.mobile)))
                    if whatsapp_messaging.domain and len(whatsapp_messaging.wa_messaging_domain) > 2:
                        to_partners |= to_partners.search(safe_eval(whatsapp_messaging.wa_messaging_domain)).filtered(lambda x: x.mobile and (x.mobile not in unique_phones and not unique_phones.add(x.mobile)))
                    to_partners = to_partners.filtered(
                        lambda x: x.mobile.lower().strip() not in whatsapp_messaging.mail_history_ids.mapped('phone'))
                    message_partner += len(to_partners)
                    if not len(to_partners):
                        raise ValueError("Not Enough contact to process")
                    # to_partners = list(split_every(2, to_partners))
                    for partner in to_partners:
                        _logger.info("contact Mobile (Whatsapp Number) %s - %s" % (partner.mobile, str(sequence)))
                        sequence += 1
                        channel = whatsapp_messaging.provider_id.get_channel_whatsapp(partner, user)
                        wa_message_values = {
                            "body": tools.html2plaintext(whatsapp_messaging.body_html) if (whatsapp_messaging.body_html and whatsapp_messaging.body_html != "") else '',
                            "author_id": user.partner_id.id,
                            "email_from": user.partner_id.email or "",
                            "isWaMsgs": True,
                            "subtype_id": self.env["ir.model.data"].sudo()._xmlid_to_res_id("mail.mt_comment"),
                            "whatsapp_messaging_id": whatsapp_messaging.id,
                            "reply_to": user.partner_id.email,
                            "attachment_ids": [(4, attac_id.id) for attac_id in whatsapp_messaging.attachment_ids],
                            "model": "discuss.channel",
                            "message_type": "wa_msgs",
                            "res_id": channel.id,
                        }
                        context_dict = {"user_id": user, "cron": True}
                        if whatsapp_messaging.template_id:
                            context_dict.update({
                                "template_send": True,
                                "wa_template": whatsapp_messaging.template_id,
                                "active_model_id": partner.id,
                                "active_model": self._name,
                                "attachment_ids": whatsapp_messaging.attachment_ids.ids,
                            })
                        wa_message_body = self.env["mail.message"].sudo().with_context(context_dict).create(
                            wa_message_values)
                        wa_message_body.chatter_wa_model = partner._name
                        wa_message_body.chatter_wa_res_id = partner.id
                        whatsapp_messaging.write({"marketing_contact_mes_history_ids": [(0, 0, {"phone": partner.mobile})]})
                        self._cr.commit()

                else:
                    vals = {
                        "provider_id": whatsapp_messaging.provider_id.id,
                        "author_id": user.partner_id.id,
                        "type": "in queue",
                        "whatsapp_messaging_id": whatsapp_messaging.id,
                        "model": self._name,
                    }
                    to_contacts = whatsapp_messaging.whatsapp_messaging_lists_ids.wa_list_contacts_ids.filtered(
                                    lambda x: x.phone and (x.phone not in unique_phones and not unique_phones.add(x.phone)))
                    to_contacts = to_contacts.filtered(
                        lambda x: x.phone not in whatsapp_messaging.mail_history_ids.mapped('phone'))
                    message_partner += len(to_contacts)
                    for to_contact in to_contacts:
                        try:
                            _logger.info("contact Mobile (Whatsapp Number) %s  -- [%s]" % (to_contact.phone, str(sequence)))
                            sequence += 1
                            if whatsapp_messaging.template_id:
                                params = []
                                object_data = False
                                for component in whatsapp_messaging.template_id.components_ids:
                                    cards = []
                                    template_dict = {}
                                    if component.type in ["body", "footer"]:
                                        if component.variables_ids:
                                            template_dict.update(
                                                {"type": component.type, "parameters": []})
                                    if component.type == "header":
                                        if component.formate == "text":
                                            if component.variables_ids:
                                                template_dict.update(
                                                    {"type": component.type, "parameters": []})

                                        if component.formate == "media":
                                            if component.formate_media_type in ["dynamic", 'static']:
                                                if component.media_type in ["image", "video", "document"] and (
                                                        whatsapp_messaging.attachment_ids or component.attachment_ids):
                                                    doc_attachment = whatsapp_messaging.attachment_ids.sudo() if component.formate_media_type == "dynamic" else (
                                                        component.attachment_ids.sudo())
                                                    parameters = whatsapp_messaging.provider_id.get_docs_parameters(
                                                        doc_type=component.media_type,
                                                        doc_id=fields.first(doc_attachment))
                                                    template_dict.update(
                                                        {"type": component.type, "parameters": parameters})
                                    if component.type == "buttons":
                                        whatsapp_messaging.template_id._get_send_button_params(component, object_data, params)
                                    if component.type == 'carousel':
                                        whatsapp_messaging.template_id._get_carousel_params(component, object_data, whatsapp_messaging.provider_id, cards)
                                    if component.type == "limited_time_offer":
                                        template_dict.update({'type': component.type})
                                        parameter = []
                                        limited_time_offer = {
                                            "type": "limited_time_offer",
                                            "limited_time_offer": {
                                                'expiration_time_ms': datetime.timestamp(
                                                    component.limited_offer_exp_date) * 1000
                                            }
                                        }
                                        parameter.append(limited_time_offer)
                                        template_dict.update({'parameters': parameter})
                                    if component.type == "interactive":
                                        params = []
                                        for component in whatsapp_messaging.template_id.components_ids:
                                            template_dict = whatsapp_messaging.provider_id._get_interactive_template_params(component)
                                            if bool(template_dict):
                                                params.append(template_dict)
                                    if bool(template_dict):
                                        params.append(template_dict)
                                    if cards:
                                        params.append({"type": "CAROUSEL", "cards": cards})
                                answer = None
                                if whatsapp_messaging.template_id.template_type == 'interactive':
                                    answer = whatsapp_messaging.provider_id.direct_send_mpm_template(
                                        whatsapp_messaging.template_id.name,
                                        whatsapp_messaging.template_id.language,
                                        whatsapp_messaging.template_id.namespace,
                                        to_contact,
                                        params)
                                else:
                                    answer = whatsapp_messaging.provider_id.direct_send_template(
                                        whatsapp_messaging.template_id.name,
                                        whatsapp_messaging.template_id.language,
                                        whatsapp_messaging.template_id.namespace,
                                        to_contact,
                                        params,
                                    )

                                if answer and answer.status_code == 200:
                                    dict = json.loads(answer.text)
                                    if "messages" in dict and dict.get("messages") and dict.get("messages")[0].get(
                                            "id"):
                                        vals.update({
                                            ""
                                            "message": tools.html2plaintext(whatsapp_messaging.body_html),
                                            "message_id": dict.get("messages")[0].get("id"),
                                            "phone": to_contact.phone,
                                        })
                                        self.env[
                                            "whatsapp.history"
                                        ].sudo().create(vals)
                            else:
                                if whatsapp_messaging.body_html and tools.html2plaintext(whatsapp_messaging.body_html) != "":
                                    if whatsapp_messaging.provider_id.provider == "graph_api":
                                        answer = whatsapp_messaging.provider_id.direct_send_message(to_contact,
                                                                                                    tools.html2plaintext(
                                                                                                        whatsapp_messaging.body_html))
                                        dict = json.loads(answer.text)
                                        if "messages" in dict and dict.get("messages") and dict.get("messages")[0].get(
                                                "id"):
                                            vals.update({
                                                "phone": to_contact.phone,
                                                "message": tools.html2plaintext(whatsapp_messaging.body_html),
                                                "message_id": dict.get("messages")[0].get("id"),
                                            })
                                            self.env["whatsapp.history"].sudo().create(vals)
                                for attachment in whatsapp_messaging.attachment_ids:
                                    if whatsapp_messaging.provider_id.provider == "graph_api":
                                        sent_type = ''
                                        if attachment.mimetype in image_type:
                                            sent_type += "image"
                                        elif attachment.mimetype in document_type:
                                            sent_type += "document"
                                        elif attachment.mimetype in audio_type:
                                            sent_type += "audio"
                                        elif attachment.mimetype in video_type:
                                            sent_type += "video"
                                        else:
                                            sent_type += "image"

                                        answer = whatsapp_messaging.provider_id.send_image(attachment)
                                        if answer.status_code == 200:
                                            dict = json.loads(answer.text)
                                            getimagebyid = whatsapp_messaging.provider_id.direct_get_image_by_id(
                                                dict.get("id"),
                                                to_contact,
                                                sent_type,
                                                attachment,
                                            )
                                            if getimagebyid.status_code == 200:
                                                imagedict = json.loads(getimagebyid.text)
                                                if "messages" in imagedict and imagedict.get("messages"):
                                                    vals.update({
                                                        "attachment_ids": [(4, attachment.id)],
                                                        "message_id": imagedict.get("id"),
                                                        "phone": to_contact.phone,
                                                    })
                                                    self.env["whatsapp.history"].sudo().create(vals)
                            whatsapp_messaging.write({"marketing_contact_mes_history_ids": [(0, 0, {"phone": to_contact.phone})
                                                                                            ]})
                            self._cr.commit()

                        except Exception as e:
                            _logger.error(e)
                            continue

                if message_partner == len(whatsapp_messaging.mail_history_ids):
                    whatsapp_messaging.write({'is_cron_run': True, "state": "done"})
                    self._cr.commit()

            except Exception as ve:
                _logger.error(f"{ve}")
                continue
