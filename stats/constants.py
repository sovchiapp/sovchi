UZ_CITIES_DISTRICTS = {
    "Toshkent shahri": (
        "Chilonzor", "Yunusobod", "Mirzo Ulug'bek", "Yakkasaroy",
        "Olmazor", "Mirobod", "Shayhontohur", "Uchtepa",
        "Sergeli", "Bektemir", "Yangihayot", "Yashnobod"
    ),
    "Toshkent viloyati": (
        "Angren", "Bekobod", "Bo'ka", "Bo'stonliq", "Chinoz",
        "Ohangaron", "Oqqo'rg'on", "Parkent", "Piskent",
        "Qibray", "Toshkent", "O'rta Chirchiq", "Yuqori Chirchiq",
        "Zangiota", "Nurafshon"
    ),
    "Andijon": (
        "Andijon shahri", "Asaka", "Baliqchi", "Bo'z", "Buloqboshi",
        "Jalolquduq", "Xo'jaobod", "Izboskan", "Marhamat",
        "Oltinko'l", "Paxtaobod", "Qo'rg'ontepa", "Shahrixon",
        "Ulug'nor", "Andijon tumani"
    ),
    "Buxoro": (
        "Buxoro shahri", "Olot", "Buxoro", "G'ijduvon", "Jondor",
        "Kogon", "Peshku", "Qorako'l", "Qorovulbozor",
        "Romitan", "Shofirkon", "Vobkent"
    ),
    "Farg'ona": (
        "Farg'ona shahri", "Beshariq", "Bog'dot", "Buvayda",
        "Dang'ara", "Farg'ona", "Furqat", "Oltiariq",
        "O'zbekiston", "Qo'qon", "Qo'shtepa", "Rishton",
        "So'x", "Toshloq", "Uchko'prik", "Yozyovon", "Marg'ilon"
    ),
    "Jizzax": (
        "Jizzax shahri", "Arnasoy", "Baxmal", "Do'stlik", "Forish",
        "G'allaorol", "Mirzacho'l", "Paxtakor", "Yangiobod",
        "Zomin", "Zarbdor", "Zafarobod"
    ),
    "Xorazm": (
        "Urganch shahri", "Bog'ot", "Gurlan", "Xiva", "Xonqa",
        "Qo'shko'pir", "Shovot", "Urganch", "Xazorasp",
        "Yangiariq", "Yangibozor"
    ),
    "Namangan": (
        "Namangan shahri", "Chortoq", "Chust", "Kosonsoy",
        "Mingbuloq", "Namangan", "Norin", "Pop",
        "To'raqo'rg'on", "Uchqo'rg'on", "Uychi", "Yangiqo'rg'on"
    ),
    "Navoiy": (
        "Navoiy shahri", "Karmana", "Konimex", "Xatirchi",
        "Navbahor", "Nurota", "Qiziltepa", "Tomdi",
        "Uchquduq", "Zarafshon shahri"
    ),
    "Qashqadaryo": (
        "Qarshi shahri", "Chiroqchi", "Dehqonobod", "G'uzor",
        "Qamashi", "Qarshi", "Kasbi", "Kitob", "Koson",
        "Mirishkor", "Muborak", "Nishon", "Shahrisabz",
        "Yakkabog'", "Guzar"
    ),
    "Qoraqalpog'iston": (
        "Nukus shahri", "Amudaryo", "Beruniy", "Chimboy",
        "Ellikqal'a", "Kegeyli", "Mo'ynoq", "Qonliko'l",
        "Qorao'zak", "Shumanay", "Taxtako'pir", "To'rtko'l",
        "Xo'jayli", "Bo'zatov", "Nukus tumani"
    ),
    "Samarqand": (
        "Samarqand shahri", "Bulungur", "Ishtixon", "Jomboy",
        "Kattaqo'rg'on", "Narpay", "Nurobod", "Oqdaryo",
        "Payariq", "Pastdarg'om", "Paxtachi", "Qo'shrabot",
        "Samarqand", "Toyloq", "Urgut"
    ),
    "Sirdaryo": (
        "Guliston shahri", "Boyovut", "Guliston", "Mirzaobod",
        "Oqoltin", "Sardoba", "Sayxunobod", "Sirdaryo", "Xovos"
    ),
    "Surxondaryo": (
        "Termiz shahri", "Angor", "Boysun", "Denov", "Jarqo'rg'on",
        "Muzrabot", "Oltinsoy", "Qiziriq", "Qumqo'rg'on",
        "Sariosiyo", "Sherobod", "Sho'rchi", "Termiz", "Uzun"
    )
}

MARITAL_STATUS_MAP = {
    "never_married": "Bo'ydoq",
    "divorced_with_children": "Ajrashgan farzandli",
    "divorced_without_children": "Ajrashgan farzandsiz",
}

EDUCATION_MAP = {
    "high_school": "O'rta maktab",
    "bachelors": "Bakalavr",
    "masters": "Magistr",
    "phd": "PhD",
    "other": "Boshqa",
}

OCCUPATION_MAP = {
    "student": "Talaba",
    "employee": "Ishchi-xodim",
    "entrepreneur": "Tadbirkor",
    "unemployed": "Ishsiz",
    "retired": "Nafaqada",
    "prefer_not_to_say": "Aytishni istamayman"
}

AGE_GROUPS = ("18-25", "26-35", "36-45", "45+")

GENDERS = (
    {"value": "M", "label": "Male"},
    {"value": "F", "label": "Female"}
)

PERIODS = ("today", "week", "month", "3_months", "6_months", "9_months", "year", "all")

PLATFORMS = ("web", "ios", "android")
