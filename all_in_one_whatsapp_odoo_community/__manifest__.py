{
    "name": "All In One Odoo WhatsApp Integration Modules | WhatsApp Base, Automation, Discuss, Marketing & Chatbot | WhatsApp Cloud API | Odoo V18 Community Edition",
    "version": "18.0",
    "author": "TechUltra Solutions Private Limited",
    "category": "Marketing",
    "live_test_url": "https://www.youtube.com/playlist?list=PL8o8i9mlxsWiGhybME4miEeftUCcTLNoj",
    "company": "TechUltra Solutions Private Limited",
    "website": "https://www.techultrasolutions.com/",
    "summary": "Odoo WhatsApp Base Module (WhatsApp Automation) | Odoo WhatsApp Discuss (Bidirectional) Module | Odoo WhatsApp Marketing Module | Odoo WhatsApp Chatbot Module",
    "description": """
        All-in-One WhatsApp Community
        All-in-One WhatsApp
        All-in-One
        Odoo WhatsApp Base Module (WhatsApp Automation)
        Odoo WhatsApp Discuss (Bidirectional) Module
        Odoo WhatsApp Marketing Module
        Odoo WhatsApp Chatbot Module
        Odoo V12 to V16 (Both Community and Enterprise Editions)
        Odoo V17 to V18 (Only in Community Version)
        Odoo 
        Odoo Community
        WhatsApp Marketing
        WhatsApp Base
        WhatsApp Discuss
        WhatsApp Chatbot
        Chatbot
        Marketing
        Odoo ERP
        V18 WhatsApp        
        Odoo WhatsApp
        WhatsApp Marketing Community
        Meta
        Facebook
        Integration
        Cloud API
        WhatsApp Cloud API
        Community
    """,
    "depends": ['base', 'mail', 'mail_group', 'base_automation'],
    "data": [
        # tus_meta_whatsapp_base
        'tus_meta_whatsapp_base/security/whatsapp_security.xml',
        'tus_meta_whatsapp_base/security/ir.model.access.csv',
        'tus_meta_whatsapp_base/data/cron.xml',
        'tus_meta_whatsapp_base/data/wa_template.xml',
        'tus_meta_whatsapp_base/wizard/wa_compose_message_view.xml',
        'tus_meta_whatsapp_base/views/provider_base.xml',
        'tus_meta_whatsapp_base/views/res_users.xml',
        'tus_meta_whatsapp_base/views/channel_provider_line.xml',
        'tus_meta_whatsapp_base/views/res_partner.xml',
        'tus_meta_whatsapp_base/views/whatsapp_history.xml',
        'tus_meta_whatsapp_base/views/wa_template.xml',
        'tus_meta_whatsapp_base/views/variables.xml',
        'tus_meta_whatsapp_base/views/components.xml',
        'tus_meta_whatsapp_base/views/mail_channel.xml',
        'tus_meta_whatsapp_base/views/mail_message.xml',
        'tus_meta_whatsapp_base/views/provider_meta.xml',
        'tus_meta_whatsapp_base/views/ir_actions.xml',
        'tus_meta_whatsapp_base/views/interactive_list_views.xml',
        'tus_meta_whatsapp_base/views/interactive_product_list_views.xml',
        'tus_meta_whatsapp_base/views/wa_button_component_views.xml',
        'tus_meta_whatsapp_base/views/wa_carousel_component_view.xml',

        # tus_meta_wa_discuss
        'tus_meta_wa_discuss/views/res_config_settings_views.xml',

        # tus_meta_wa_marketing
        "tus_meta_wa_marketing/security/ir.model.access.csv",
        "tus_meta_wa_marketing/security/security.xml",
        "tus_meta_wa_marketing/data/whatsapp_messaging_data.xml",
        "tus_meta_wa_marketing/wizard/whatsapp_messaging_schedule_date_views.xml",
        "tus_meta_wa_marketing/wizard/test_whatsapp_marketing_views.xml",
        "tus_meta_wa_marketing/views/whatsapp_messaging_view.xml",
        "tus_meta_wa_marketing/views/whatsapp_messaging_lists_view.xml",
        "tus_meta_wa_marketing/views/whatsapp_messaging_lists_contacts_vies.xml",

        # odoo_whatsapp_chatbot
        "odoo_whatsapp_chatbot/security/ir.model.access.csv",
        "odoo_whatsapp_chatbot/data/wa_template.xml",
        "odoo_whatsapp_chatbot/data/whatsapp_chatbot.xml",
        "odoo_whatsapp_chatbot/views/whatsapp_chatbot_script_views.xml",
        "odoo_whatsapp_chatbot/views/mail_channel_views.xml",
        "odoo_whatsapp_chatbot/views/whatsapp_chatbot_views.xml",
        "odoo_whatsapp_chatbot/views/whatsapp_ir_action_views.xml",
        "odoo_whatsapp_chatbot/views/res_config_settings_views.xml",
    ],
    'assets': {
        'web.assets_backend': [
            # tus_meta_whatsapp_base
            'all_in_one_whatsapp_odoo_community/static/tus_meta_whatsapp_base/static/src/css/style.css',
            'all_in_one_whatsapp_odoo_community/static/tus_meta_whatsapp_base/static/src/scss/kanban_view.scss',

            #tus_meta_wa_discuss
            'all_in_one_whatsapp_odoo_community/static/tus_meta_wa_discuss/static/src/xml/message.xml',
            'all_in_one_whatsapp_odoo_community/static/tus_meta_wa_discuss/static/src/xml/AgentsList.xml',
            # 'all_in_one_whatsapp_odoo_community/static/tus_meta_wa_discuss/static/src/xml/channel_load.xml',
            'all_in_one_whatsapp_odoo_community/static/tus_meta_wa_discuss/static/src/js/common/**/*',
            'all_in_one_whatsapp_odoo_community/static/tus_meta_wa_discuss/static/src/js/agents/**/*',
            'all_in_one_whatsapp_odoo_community/static/tus_meta_wa_discuss/static/src/scss/*.scss',
            'all_in_one_whatsapp_odoo_community/static/tus_meta_wa_discuss/static/src/js/templates/**/*',
            'all_in_one_whatsapp_odoo_community/static/tus_meta_wa_discuss/static/src/core/common/**/*',
            'all_in_one_whatsapp_odoo_community/static/tus_meta_wa_discuss/static/src/core/web/**/*',

            # odoo_whatsapp_chatbot
            'all_in_one_whatsapp_odoo_community/static/odoo_whatsapp_chatbot/static/src/scss/kanban_view.scss'
        ],
    },
    "price": 199,
    "currency": "USD",
    "installable": True,
    "auto_install": False,
    "license": "OPL-1",
    "images": ["static/description/banner.gif"],
}
