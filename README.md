# Avar Wordforms

Репозиторий для сбора и агрегации **словоформ** аварского языка из разных корпусов и словарей.

## Быстрый старт

```bash
./build.sh
```

Результат:

- `output/wordforms.csv` — агрегированный список словоформ
- `output/stats.json` — статистика сборки (JSON)
- `output/stats.txt` — статистика сборки (человекочитаемый отчёт)
- `docs/` — статический сайт для GitHub Pages

Требования: Python 3.10+, без внешних зависимостей.

## Сайт (GitHub Pages)

`./build.sh` также собирает данные для сайта в `docs/data/`.

- **Поиск** — `docs/index.html`: search-suggest, 10 случайных словоформ на главной
- **Статистика** — `docs/stats.html`: графики и цифры

Публикация: GitHub → Settings → Pages → Branch `main`, folder `/docs`.

## Формат CSV

| Колонка | Описание |
|---------|----------|
| `wordform` | Словоформа |
| `lemma` | Лемма / базовое слово (может быть пустым) |
| `relation` | Тип связи: падеж, масдар, деепричастие и т.д. |
| `pos` | Часть речи словоформы |
| `source` | Название источника |
| `count` | Сколько раз встретилось при сборке |

Пример:

```csv
wordform,lemma,relation,pos,source,count
квачан,квачазе,деепричастие,глагол,AV-RU словарь Гимбатова,22
```

Если слово или связь не удалось определить — поле остаётся пустым.

## Структура проекта

```
avar/forms/
├── build.sh                    # Мастер-скрипт сборки
├── config/
│   └── sources.json            # Реестр всех источников
├── mappings/                   # Ручные уточнения маппинга
│   └── gimbatov.overrides.json
├── sources/                    # Исходные данные
│   └── gimbatov.av-ru.enriched.jsonl
├── avarforms/                  # Python-фреймворк
│   ├── core/                   # Модели, пайплайн, статистика
│   ├── sources/                # Экстракторы по источникам
│   └── cli.py
└── output/                     # Артефакты сборки (gitignore)
```

## Источники

Источники описываются в `config/sources.json`:

```json
{
  "id": "gimbatov",
  "name": "AV-RU словарь Гимбатова",
  "enabled": true,
  "module": "avarforms.sources.gimbatov",
  "class": "GimbatovExtractor",
  "config": {
    "path": "sources/gimbatov.av-ru.enriched.jsonl"
  }
}
```

### AV-RU словарь Гимбатова

Экстрактор `GimbatovExtractor` извлекает словоформы из четырёх подисточников:

| Подисточник | Описание | Качество |
|-------------|----------|----------|
| `explicit_relation` | Записи с явной связью (`masdarfrom`, `pluralfor`, `genitivefrom`, `deverbfrom` …) | Высокое |
| `forms` | Парадигмы из поля `forms` | Высокое (лемма известна, падеж часто нет) |
| `gender_forms` | Родовые формы | Высокое |
| `examples` | Токены из примеров (`av`) | Среднее — матч по индексу словаря |

Поддерживаемые ключи связи:

- `masdarfrom`, `masdarforceto` → масдар
- `pluralfor` → множественное число
- `genitivefrom`, `dativefrom`, `locativefrom`, `ablativefrom`, `ergativefrom` → падежи
- `participlefrom` → причастие
- `deverbfrom` → деепричастие
- `forceto` → понудительная форма

## Добавление нового источника

1. Положите данные в `sources/`
2. Создайте экстрактор в `avarforms/sources/my_source.py`:

```python
from typing import Iterator
from avarforms.core.extractor import SourceExtractor
from avarforms.core.models import MappingTable, WordFormRecord

class MySourceExtractor(SourceExtractor):
    def extract(self, mappings: MappingTable | None = None) -> Iterator[WordFormRecord]:
        # yield WordFormRecord(
        #     wordform="...",
        #     lemma="...",
        #     relation="...",
        #     pos="...",
        #     source=self.source_name,
        #     subsource="...",
        # )
        ...
```

3. Зарегистрируйте в `config/sources.json`
4. При необходимости добавьте файл маппинга в `mappings/` и укажите его в секции `"mappings"`

5. Запустите `./build.sh`

## Улучшение маппинга

Файлы в `mappings/` позволяют вручную уточнять связи словоформа → лемма. Формат:

```json
{
  "description": "Ручные уточнения",
  "wordforms": {
    "квачан": {
      "lemma": "квачазе",
      "relation": "деепричастие",
      "pos": "глагол"
    },
    "простаяформа": "лемма"
  }
}
```

Маппинги применяются поверх автоматического извлечения и имеют приоритет.

Добавьте путь к файлу в `config/sources.json`:

```json
"mappings": [
  "mappings/gimbatov.overrides.json",
  "mappings/my_new_maps.json"
]
```

## Статистика

После сборки смотрите `output/stats.txt`:

- количество записей по источникам и подисточникам
- сколько записей без леммы / связи / части речи
- топ лемм, словоформ и типов связей
- «странные» записи (аномалии для ручной проверки)

## Разработка

```bash
export PYTHONPATH=.
python3 -m avarforms.cli
python3 -m avarforms.cli --root /path/to/project
```

Установка как пакет (опционально):

```bash
pip install -e .
avarforms-build
```
