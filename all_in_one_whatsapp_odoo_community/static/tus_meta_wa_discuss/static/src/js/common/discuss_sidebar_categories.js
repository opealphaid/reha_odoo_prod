/* @odoo-module */

import { discussSidebarChannelIndicatorsRegistry } from "@mail/discuss/core/public_web/discuss_sidebar_categories";
import { patch } from "@web/core/utils/patch";
import { DiscussAppCategory } from "@mail/core/public_web/discuss_app_category_model";
import { compareDatetime } from "@mail/utils/common/misc";

//discussSidebarChannelIndicatorsRegistry.add(
//    "WpChannels",
//    {
//        predicate: (store) => store.discuss.WpChannels.threads.some((thread) => thread?.is_pinned),
//        value: (store) => store.discuss.WpChannels,
//     },
//    { sequence: 30 }
//);
