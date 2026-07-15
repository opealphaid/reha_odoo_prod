/** @odoo-module **/

import { HtmlField, htmlField } from "@web_editor/js/backend/html_field";
import { registry } from "@web/core/registry";
import { formatText } from "@mail/js/emojis_mixin";
import { markup } from "@odoo/owl";

export class FieldPostPreview extends HtmlField {
    get markupValue() {
        var result = this.props.record.data[this.props.name];
        const $html = $(result + "");
        var $previewMessage = $html.find(".viin_social_preview_message");
        $previewMessage.html(formatText($previewMessage.text().trim()));

        return markup($html[0].outerHTML);
    }
}

export const fieldPostPreview = {
    ...htmlField,
    component: FieldPostPreview,
};

registry.category("fields").add("viin_social_post_preview", fieldPostPreview);
