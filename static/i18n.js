'use strict';
/* Interface language for the seller app: English and Bahasa Melayu. */

const I18N = {
  en: {
    'nav.orders': 'Orders', 'nav.parser': 'Message reader', 'nav.recipes': 'Recipes & costing',
    'nav.production': 'Production plan', 'nav.grocery': 'Grocery list', 'nav.profit': 'Profit & loss',
    'nav.inbox': 'Message box', 'nav.settings': 'Settings',
    'title.orders': 'Orders', 'title.parser': 'Read a customer message', 'title.recipes': 'Recipes & ingredient costing',
    'title.production': 'Production plan', 'title.grocery': 'Grocery list', 'title.profit': 'Profit & loss',
    'title.inbox': 'Message box', 'title.settings': 'Settings',
    'sub.orders': 'Every active order, payment and delivery in one place.',
    'sub.parser': 'Paste a customer message. Code checks every field before you approve it.',
    'sub.recipes': 'Raw materials, pack prices, and what one piece really costs.',
    'sub.production': 'How many batches to cook for a date.',
    'sub.grocery': 'What to buy, for a day or a week of production.',
    'sub.profit': 'Revenue, ingredient cost and net profit per order.',
    'sub.inbox': 'Customers order here; you reply here.',
    'sub.settings': 'Your shop, your menu, and the language of this screen.',
    'action.newOrder': 'New order', 'action.addIngredient': 'Add ingredient', 'action.newRecipe': 'New recipe',
    'action.parse': 'Read the message', 'action.approve': 'Approve', 'action.reject': 'Reject',
    'action.send': 'Send', 'action.copyLink': 'Copy customer link', 'action.save': 'Save',
    'action.newLink': 'New link', 'action.open': 'Open', 'action.add': 'Add', 'action.close': 'Close',
    'action.signOut': 'Sign out', 'action.review': 'Review', 'action.copy': 'Copy link',
    'dash.active': 'Active orders', 'dash.unpaid': 'Unpaid', 'dash.profit': 'Net profit · month',
    'dash.waiting': 'Waiting for you', 'dash.dueToday': 'due today', 'dash.chase': 'chase before delivery',
    'dash.revenue': 'revenue', 'dash.margin': 'margin', 'dash.drafts': 'parsed drafts', 'dash.unread': 'unread messages',
    'table.customer': 'Customer', 'table.delivery': 'Delivery', 'table.items': 'Items', 'table.status': 'Status',
    'table.payment': 'Payment', 'table.total': 'Total', 'table.when': 'When', 'table.feature': 'Feature',
    'table.model': 'Model', 'table.tokens': 'Tokens', 'table.outcome': 'Outcome', 'table.ms': 'ms',
    'common.search': 'Search customer, product, address', 'common.product': 'Product', 'common.qty': 'Qty',
    'common.price': 'Price', 'common.all': 'All orders', 'common.nextDeliveries': 'Next deliveries',
    'common.drafts': 'Parsed drafts', 'common.nothing': 'Nothing here yet.',
    'setting.business': 'Shop profile', 'setting.businessHint': 'The name buyers see, and the contact on the shop page.',
    'setting.name': 'Shop name', 'setting.tagline': 'Tagline', 'setting.phone': 'Phone', 'setting.address': 'Address',
    'setting.menu': 'Menu', 'setting.menuHint': 'What buyers can order, and the price you sell it at.',
    'setting.menuName': 'Dish', 'setting.menuPrice': 'Price (RM)', 'setting.menuCategory': 'Category',
    'setting.menuDescription': 'Short description', 'setting.addDish': 'Add dish', 'setting.noDishes': 'No dishes yet. Add the first one.',
    'setting.shopLink': 'Shop link', 'setting.shopHint': 'Send this link to customers. They order without an account.',
    'setting.language': 'Language', 'setting.languageHint': 'The language of this dashboard.',
    'setting.account': 'Account', 'setting.support': 'Support',
    'setting.recipeIdeas': 'Recipe ideas', 'setting.recipeIdeasHint': 'Researched when a buyer orders a dish with no recipe.',
    'setting.approveCost': 'Approve & cost', 'setting.noIdeas': 'No recipe ideas waiting.',
    'language.en': 'English', 'language.bm': 'Bahasa Melayu',
    'empty.orders': 'No orders yet', 'empty.ordersText': 'Paste a customer message into the parser, or share your shop link.',
    'empty.drafts': 'No drafts waiting', 'empty.draftsText': 'Orders from your shop link land here for approval.',
    'notify.title': 'Notifications', 'notify.empty': 'Nothing new.', 'notify.clear': 'Mark all read',
  },
  bm: {
    'nav.orders': 'Tempahan', 'nav.parser': 'Baca mesej', 'nav.recipes': 'Resipi & kos',
    'nav.production': 'Pelan pengeluaran', 'nav.grocery': 'Senarai beli', 'nav.profit': 'Untung & rugi',
    'nav.inbox': 'Kotak mesej', 'nav.settings': 'Tetapan',
    'title.orders': 'Tempahan', 'title.parser': 'Baca mesej pelanggan', 'title.recipes': 'Resipi & kos bahan',
    'title.production': 'Pelan pengeluaran', 'title.grocery': 'Senarai beli', 'title.profit': 'Untung & rugi',
    'title.inbox': 'Kotak mesej', 'title.settings': 'Tetapan',
    'sub.orders': 'Semua tempahan aktif, bayaran dan tarikh hantar di satu tempat.',
    'sub.parser': 'Tampal mesej pelanggan. Setiap ruang disemak sebelum anda luluskan.',
    'sub.recipes': 'Bahan mentah, harga pek, dan kos sebenar sebiji.',
    'sub.production': 'Berapa adunan untuk dimasak pada satu tarikh.',
    'sub.grocery': 'Apa nak beli, untuk sehari atau seminggu.',
    'sub.profit': 'Jualan, kos bahan dan untung bersih setiap tempahan.',
    'sub.inbox': 'Pelanggan tempah di sini; anda balas di sini.',
    'sub.settings': 'Kedai anda, menu anda, dan bahasa skrin ini.',
    'action.newOrder': 'Tempahan baru', 'action.addIngredient': 'Tambah bahan', 'action.newRecipe': 'Resipi baru',
    'action.parse': 'Baca mesej', 'action.approve': 'Luluskan', 'action.reject': 'Tolak',
    'action.send': 'Hantar', 'action.copyLink': 'Salin pautan pelanggan', 'action.save': 'Simpan',
    'action.newLink': 'Pautan baru', 'action.open': 'Buka', 'action.add': 'Tambah', 'action.close': 'Tutup',
    'action.signOut': 'Keluar', 'action.review': 'Semak', 'action.copy': 'Salin pautan',
    'dash.active': 'Tempahan aktif', 'dash.unpaid': 'Belum bayar', 'dash.profit': 'Untung bersih · bulan',
    'dash.waiting': 'Menunggu anda', 'dash.dueToday': 'hari ini', 'dash.chase': 'kejar sebelum hantar',
    'dash.revenue': 'jualan', 'dash.margin': 'margin', 'dash.drafts': 'draf dihurai', 'dash.unread': 'mesej belum dibaca',
    'table.customer': 'Pelanggan', 'table.delivery': 'Hantar', 'table.items': 'Item', 'table.status': 'Status',
    'table.payment': 'Bayaran', 'table.total': 'Jumlah', 'table.when': 'Bila', 'table.feature': 'Ciri',
    'table.model': 'Model', 'table.tokens': 'Token', 'table.outcome': 'Hasil', 'table.ms': 'ms',
    'common.search': 'Cari pelanggan, produk, alamat', 'common.product': 'Produk', 'common.qty': 'Bil',
    'common.price': 'Harga', 'common.all': 'Semua tempahan', 'common.nextDeliveries': 'Hantaran seterusnya',
    'common.drafts': 'Draf dihurai', 'common.nothing': 'Belum ada apa-apa.',
    'setting.business': 'Profil kedai', 'setting.businessHint': 'Nama yang pelanggan lihat, dan kenalan di halaman kedai.',
    'setting.name': 'Nama kedai', 'setting.tagline': 'Slogan', 'setting.phone': 'Telefon', 'setting.address': 'Alamat',
    'setting.menu': 'Menu', 'setting.menuHint': 'Apa pelanggan boleh tempah, dan harga jualan anda.',
    'setting.menuName': 'Hidangan', 'setting.menuPrice': 'Harga (RM)', 'setting.menuCategory': 'Kategori',
    'setting.menuDescription': 'Penerangan ringkas', 'setting.addDish': 'Tambah hidangan', 'setting.noDishes': 'Belum ada hidangan. Tambah yang pertama.',
    'setting.shopLink': 'Pautan kedai', 'setting.shopHint': 'Hantar pautan ini kepada pelanggan. Mereka tempah tanpa akaun.',
    'setting.language': 'Bahasa', 'setting.languageHint': 'Bahasa papan pemuka ini.',
    'setting.account': 'Akaun', 'setting.support': 'Sokongan',
    'setting.recipeIdeas': 'Idea resipi', 'setting.recipeIdeasHint': 'Dikaji bila pelanggan tempah hidangan tanpa resipi.',
    'setting.approveCost': 'Luluskan & kos', 'setting.noIdeas': 'Tiada idea resipi menunggu.',
    'language.en': 'English', 'language.bm': 'Bahasa Melayu',
    'empty.orders': 'Belum ada tempahan', 'empty.ordersText': 'Tampal mesej pelanggan di pembaca, atau kongsikan pautan kedai.',
    'empty.drafts': 'Tiada draf menunggu', 'empty.draftsText': 'Tempahan dari pautan kedai masuk ke sini untuk diluluskan.',
    'notify.title': 'Notifikasi', 'notify.empty': 'Tiada yang baru.', 'notify.clear': 'Tanda semua dibaca',
  },
};

let LANG = localStorage.getItem('nivora_lang') || 'en';

function t(key) {
  return (I18N[LANG] && I18N[LANG][key]) || I18N.en[key] || key;
}

function setLang(lang) {
  LANG = I18N[lang] ? lang : 'en';
  localStorage.setItem('nivora_lang', LANG);
  document.documentElement.lang = LANG === 'bm' ? 'ms' : 'en';
}

setLang(LANG);
