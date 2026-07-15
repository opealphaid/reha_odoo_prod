from odoo import models, fields, api
from odoo.exceptions import ValidationError
from odoo.addons.all_in_one_whatsapp_odoo_community.tus_meta_whatsapp_base.models.whatsapp_history import image_type, video_type, audio_type, document_type


class WaCarouselComponent(models.Model):
    _name = 'wa.carousel.component'
    _description = "Whatsapp carousel Template"

    header_formate = fields.Selection([('image', 'Image'),
                                       ('video', 'Video')])

    attachment_ids = fields.Many2many('ir.attachment', string="Attach Document")
    carousel_body = fields.Text("Body")
    wa_button_ids = fields.One2many('wa.button.component', 'carousel_id', string="Buttons")
    component_id = fields.Many2one('components')
    variables_ids = fields.One2many('variables', 'carousel_id', 'Variables')
    model_id = fields.Many2one('ir.model', related="component_id.model_id")

    @api.onchange('attachment_ids')
    def onchange_check_attachment(self):
        for rec in self:
            if rec.attachment_ids:
                for attachment_id in rec.attachment_ids:
                    if rec.header_formate == 'video':
                        if attachment_id.mimetype not in video_type:
                            raise ValidationError("Invalid type %s for video" % attachment_id.mimetype)
                    if rec.header_formate == 'image':
                        if attachment_id.mimetype not in image_type:
                            raise ValidationError("Invalid type %s for image" % attachment_id.mimetype)
