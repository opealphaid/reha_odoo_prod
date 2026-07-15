from odoo import api, models


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    @api.model_create_multi
    def create(self, vals_list):
        from .. import get_viin_brand_module_icon, check_viin_brand_module_icon, _build_viin_web_icon_path_from_image

        for vals in vals_list:
            if 'web_icon' in vals:
                web_icon = vals.get('web_icon')
                paths = web_icon.split(',') if web_icon and isinstance(web_icon, str) else []
                if len(paths) == 2:
                    if check_viin_brand_module_icon(paths[0]):
                        img_path = get_viin_brand_module_icon(paths[0])
                        vals['web_icon'] = _build_viin_web_icon_path_from_image(img_path)
        return super(IrUiMenu, self).create(vals_list)

    def write(self, vals):
        from .. import get_viin_brand_module_icon, check_viin_brand_module_icon, _build_viin_web_icon_path_from_image

        if 'web_icon' in vals:
            web_icon = vals.get('web_icon')
            paths = web_icon.split(',') if web_icon and isinstance(web_icon, str) else []
            if len(paths) == 2:
                if check_viin_brand_module_icon(paths[0]):
                    img_path = get_viin_brand_module_icon(paths[0])
                    vals['web_icon'] = _build_viin_web_icon_path_from_image(img_path)
        return super(IrUiMenu, self).write(vals)
