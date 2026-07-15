/* @odoo-module */

import { Message } from "@mail/core/common/message";
import { url } from "@web/core/utils/urls";
import { assignDefined } from "@mail/utils/common/misc";
import { patch } from "@web/core/utils/patch";

patch(Message.prototype, {
    get authorAvatarUrl() {
        var avatar_url = super.authorAvatarUrl;
        if (this.props.thread?.type === "social_chat" && this.message.author === undefined) {
            return url(
                `/discuss/channel/${this.props.thread.id}/avatar_128`,
                assignDefined({}, { unique: this.avatarCacheKey })
            );
        }
        return avatar_url;
    },
});
