"""UI strings, RU/EN. S(key) returns the string for the active language.
Backend messages (journal, EXT_CSD descriptions, file statuses) stay as
they arrive; only static UI text is localized."""

_LANG = "en"

STRINGS = {
    # tabs
    "tab_emmc": {"en": "EMMC", "ru": "EMMC"},
    "tab_nand": {"en": "NAND [SOON]", "ru": "NAND [СКОРО]"},
    "tab_spi": {"en": "SPI [SOON]", "ru": "SPI [СКОРО]"},
    "mode_nand_soon": {"en": "NAND Flash mode is under development",
                       "ru": "Режим NAND Flash в разработке"},
    "mode_spi_soon": {"en": "SPI Flash mode is under development",
                      "ru": "Режим SPI Flash в разработке"},

    # toolbar
    "vccq": {"en": "VCCQ 1.8V:", "ru": "VCCQ 1.8В:"},
    "bus": {"en": "Bus:", "ru": "Шина:"},
    "clock": {"en": "Clock:", "ru": "Частота:"},
    "preset": {"en": "Preset:", "ru": "Пресет:"},
    "preset_standard": {"en": "standard", "ru": "стандартный"},
    "preset_auto": {"en": "Auto", "ru": "Авто"},
    "clock_8": {"en": "8 MHz", "ru": "8 МГц"},
    "clock_16": {"en": "16 MHz", "ru": "16 МГц"},
    "clock_20": {"en": "20 MHz", "ru": "20 МГц"},
    "clock_30": {"en": "30 MHz", "ru": "30 МГц"},
    "clock_30_exp": {"en": "30 MHz (exp.)", "ru": "30 МГц (эксп.)"},

    # READ tab
    "sub_read": {"en": "READ", "ru": "ЧТЕНИЕ"},
    "sub_write": {"en": "WRITE", "ru": "ЗАПИСЬ"},
    "sub_erase": {"en": "ERASE", "ru": "СТИРАНИЕ"},
    "verify_read": {"en": "Verify after read", "ru": "Верификация после чтения"},
    "btn_init": {"en": "INIT EMMC", "ru": "ИНИТ eMMC"},
    "btn_read_userdata": {"en": "READ USERDATA", "ru": "ЧТЕНИЕ USERDATA"},
    "btn_full_read": {"en": "FULL READ (BOOT1 + BOOT2 + USERDATA)",
                      "ru": "ПОЛНОЕ ЧТЕНИЕ (BOOT1 + BOOT2 + USERDATA)"},
    "partitions": {"en": "PARTITIONS", "ru": "РАЗДЕЛЫ"},
    "col_lba": {"en": "LBA range", "ru": "Диапазон LBA"},
    "col_size": {"en": "Size", "ru": "Размер"},
    "col_name": {"en": "Name", "ru": "Имя"},
    "no_part_data": {"en": "No partition data - run INIT EMMC first",
                     "ru": "Нет данных разделов - выполните ИНИТ eMMC"},
    "selected_none": {"en": "Selected: none", "ru": "Выбрано: ничего"},
    "selected_one": {"en": "Selected: {}  LBA {}..{}",
                     "ru": "Выбрано: {}  LBA {}..{}"},
    "selected_many": {"en": "Selected: {} rows  LBA {}..{}",
                      "ru": "Выбрано: {} строк  LBA {}..{}"},
    "sel_hint": {"en": "Click - select, Ctrl+click - add/remove, Shift+click - range",
                 "ru": "Клик - выбор, Ctrl+клик - добавить/убрать, Shift+клик - диапазон"},
    "btn_dump": {"en": "DUMP", "ru": "ДАМП"},
    "btn_write": {"en": "WRITE", "ru": "ЗАПИСЬ"},
    "btn_erase": {"en": "ERASE", "ru": "СТИРАНИЕ"},

    # WRITE tab
    "verify_write": {"en": "Verify after write", "ru": "Верификация после записи"},
    "erase_before": {"en": "Erase before write (whole selected area)",
                     "ru": "Стирание перед записью (вся выбранная область)"},
    "images_folder": {"en": "IMAGES FOLDER", "ru": "ПАПКА ОБРАЗОВ"},
    "no_folder": {"en": "No folder selected", "ru": "Папка не выбрана"},
    "browse": {"en": "Browse...", "ru": "Обзор..."},
    "btn_refresh": {"en": "Refresh files", "ru": "Обновить файлы"},
    "btn_write_chip": {"en": "WRITE CHIP (BOOT1 + BOOT2 + USERDATA + selected EXT_CSD)",
                       "ru": "ЗАПИСЬ ЧИПА (BOOT1 + BOOT2 + USERDATA + выбранный EXT_CSD)"},
    "write_rules": {"en": "Smaller image = warning, larger = error. "
                         "Userdata covers the whole User Area.",
                    "ru": "Меньший образ = предупреждение, больший = ошибка. "
                          "Userdata покрывает всю User Area."},
    "not_selected": {"en": "{} not selected", "ru": "{} не выбран"},
    "extcsd_fields": {"en": "EXT_CSD FIELDS", "ru": "ПОЛЯ EXT_CSD"},
    "col_field": {"en": "Field", "ru": "Поле"},
    "col_chip": {"en": "Chip", "ru": "Чип"},
    "col_file": {"en": "File", "ru": "Файл"},
    "col_new": {"en": "New", "ru": "Новое"},
    "col_action": {"en": "Action", "ru": "Действие"},
    "btn_open_file": {"en": "Open file", "ru": "Открыть файл"},
    "btn_compare": {"en": "Compare", "ru": "Сравнить"},
    "btn_save_snapshot": {"en": "Save snapshot", "ru": "Сохранить снимок"},
    "btn_field_read": {"en": "Read", "ru": "Читать"},
    "btn_field_write": {"en": "Write", "ru": "Записать"},

    # ERASE tab
    "hardware_erase": {"en": "HARDWARE ERASE", "ru": "АППАРАТНОЕ СТИРАНИЕ"},
    "area": {"en": "Area:", "ru": "Область:"},
    "area_user_all": {"en": "User Area (All)", "ru": "User Area (вся)"},
    "start_lba": {"en": "Start LBA:", "ru": "Начальный LBA:"},
    "end_lba": {"en": "End LBA:", "ru": "Конечный LBA:"},
    "btn_erase_area": {"en": "ERASE SELECTED AREA", "ru": "СТЕРЕТЬ ВЫБРАННУЮ ОБЛАСТЬ"},

    # log panel
    "operation_log": {"en": "OPERATION LOG", "ru": "ЖУРНАЛ ОПЕРАЦИЙ"},
    "btn_copy": {"en": "Copy", "ru": "Копировать"},
    "btn_clear": {"en": "Clear", "ru": "Очистить"},
    "search_hint": {"en": "Search in log", "ru": "Поиск в журнале"},
    "log_level_all": {"en": "All", "ru": "Все"},
    "log_lines_fmt": {"en": "{} lines ({} total)", "ru": "{} строк ({} всего)"},
    "log_ready": {"en": "Ready. Select memory and mode.",
                  "ru": "Готово. Выберите память и режим."},

    # header / dialogs
    "state_label": {"en": "XGecu State:", "ru": "Состояние XGecu:"},
    "firmware_label": {"en": "Firmware:", "ru": "Прошивка:"},
    "confirm": {"en": "Confirm", "ru": "Подтверждение"},
    "confirm_plan": {"en": "Confirm EXT_CSD plan", "ru": "Подтверждение плана EXT_CSD"},
    "yes": {"en": "Yes", "ru": "Да"},
    "no": {"en": "No", "ru": "Нет"},

    # dialog titles
    "dlg_save_userdata": {"en": "Save User Area image", "ru": "Сохранить образ User Area"},
    "dlg_save_part": {"en": "Save {}", "ru": "Сохранить {}"},
    "dlg_image_for": {"en": "Image file for {}", "ru": "Файл образа для {}"},
    "dlg_dump_folder": {"en": "Folder for Boot1.bin, Boot2.bin and userdata.img",
                        "ru": "Папка для Boot1.bin, Boot2.bin и userdata.img"},
    "dlg_dump_n": {"en": "Folder for {} partition dumps", "ru": "Папка для дампов {} разделов"},
    "dlg_images_folder": {"en": "Images folder (boot1/boot2/userdata)",
                          "ru": "Папка образов (boot1/boot2/userdata)"},
    "dlg_image_area": {"en": "Image for {}", "ru": "Образ для {}"},
    "dlg_extcsd_file": {"en": "EXT_CSD file (512 / 544 bytes)",
                        "ru": "Файл EXT_CSD (512 / 544 байта)"},
    "dlg_save_extcsd": {"en": "Save EXT_CSD snapshot", "ru": "Сохранить снимок EXT_CSD"},
    "dlg_scatter": {"en": "MTK scatter file (XML or TXT)", "ru": "Файл scatter MTK (XML или TXT)"},
    "dlg_save_gpt": {"en": "Save generated GPT image (LBA 0..33)",
                     "ru": "Сохранить сгенерированный GPT-образ (LBA 0..33)"},
}


def set_lang(lang):
    global _LANG
    _LANG = lang if lang in ("ru", "en") else "en"


def get_lang():
    return _LANG


def S(key):
    entry = STRINGS.get(key)
    if entry is None:
        return key
    return entry.get(_LANG, entry.get("en", key))


# Backend statuses arrive in Russian; translate the known set for EN.
# Prefix rules cover templated messages, exact map covers fixed ones.
_BACKEND_EXACT = {
    "Выберите папку или файл": "Select an images folder or file",
    "Ошибка: файл не найден": "Error: file not found",
    "Ошибка: файл пуст": "Error: file is empty",
    "Для проверки размера выполните «Анализ eMMC»": "Run INIT EMMC to check sizes",
    "Ошибка: последний блок записи выходит за границы области":
        "Error: last write block exceeds the area",
}
_BACKEND_PREFIX = [
    ("Ошибка чтения файла: ", "File read error: "),
    ("Ошибка: файл больше области (", "Error: file larger than area ("),
    ("Предупреждение: файл меньше области (", "Warning: file smaller than area ("),
    ("Размер совпадает: ", "Size matches: "),
    ("Ошибка EXT_CSD: ", "EXT_CSD error: "),
    ("EXT_CSD: ", "EXT_CSD: "),
]


def T(text):
    """Best-effort translation of a backend status string."""
    if _LANG != "en" or not isinstance(text, str):
        return text
    if text in _BACKEND_EXACT:
        return _BACKEND_EXACT[text]
    for ru, en in _BACKEND_PREFIX:
        if text.startswith(ru):
            return en + text[len(ru):]
    return text
