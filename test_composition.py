"""Composition («Состав») text -> ingredients, percents, flags and the lines a product card shows; nutrition text -> numbers.
Run: .venv/bin/python -B -m unittest -v test_composition"""
import unittest

from grocery import composition

CHOC = ("Состав: какао тёртое, сахар, масло какао, эмульгатор (лецитин соевый), ароматизатор ванилин. "
        "Какао-продукты не менее 72%. Может содержать следы орехов.")


class ParseTests(unittest.TestCase):
    def test_chocolate(self):
        self.assertEqual(composition.parse(CHOC), {
            "ingredients": ["какао тёртое", "сахар", "масло какао", "эмульгатор (лецитин соевый)", "ароматизатор ванилин"],
            "percents": {}, "traces": "Может содержать следы орехов", "notes": ["Какао-продукты не менее 72%"]})

    def test_split_only_at_top_level(self):
        """Not inside () or [], not in «3,2»; «;» splits too; a stray «)» does not break the count; empty parts go."""
        self.assertEqual(composition.parse("СОСТАВ - томаты (60%), вода; соль [морская, йодированная], масло 3,2%, перец 1, 5 г) , ."), {
            "ingredients": ["томаты (60%)", "вода", "соль [морская, йодированная]", "масло 3,2%", "перец 1", "5 г)"],
            "percents": {"томаты (60%)": 60.0, "масло 3,2%": 3.2}, "traces": "", "notes": []})

    def test_percent_outside_brackets_wins(self):
        self.assertEqual(composition.parse("фарш 70% (свинина 40%, говядина 30%), вода")["percents"],
                         {"фарш 70% (свинина 40%, говядина 30%)": 70.0})

    def test_notes_after_the_list(self):
        self.assertEqual(composition.parse("Состав: молоко нормализованное 3,2%. Пищевая ценность на 100 г: белки 3 г. Срок годности 10 суток."), {
            "ingredients": ["молоко нормализованное 3,2%"], "percents": {"молоко нормализованное 3,2%": 3.2}, "traces": "",
            "notes": ["Пищевая ценность на 100 г: белки 3 г", "Срок годности 10 суток"]})

    def test_every_trace_phrase(self):
        self.assertEqual(composition.parse("мука пшеничная, вода. Возможно наличие следов кунжута. Может содержать следы орехов."), {
            "ingredients": ["мука пшеничная", "вода"], "percents": {}, "traces": "Возможно наличие следов кунжута; Может содержать следы орехов",
            "notes": []})

    def test_empty(self):
        for text in ("состав.", "", None):
            self.assertEqual(composition.parse(text), {"ingredients": [], "percents": {}, "traces": "", "notes": []}, text)


class PercentTests(unittest.TestCase):
    def test_share_of_an_ingredient(self):
        for word, text, share in (("какао", CHOC, 72.0),
                                  ("какао", "какао тертое 55%, какао-продукты не менее 70%", 70.0),      # the largest
                                  ("какао", "Шоколад тёмный Ritter Sport 74% какао; % содержания какао: 0", 74.0),
                                  ("какао", "Тип продукта: Шоколад; % содержания какао: 72", 72.0),
                                  ("томат", "74% томатов, вода", 74.0),
                                  ("какао", "какао 0%, какао 120%", None),                               # not a share
                                  ("а", "а 5%", 5.0),                                                    # all vowels
                                  ("сок", "сок яблочный", None), ("какао", None, None)):
            self.assertEqual(composition.percent_of(word, text), share, (word, text))


class FlagsTests(unittest.TestCase):
    def test_facts(self):
        for text, facts in (
                (CHOC, ["сахар — 2-й из 5", "ароматизатор"]),
                ("какао тертое, мед, масло какао", ["сахар как «мед» — 2-й из 3"]),
                ("скумбрия, томатный соус (паста томатная, сахар, соль)", ["сахар внутри «томатный соус» (2-й компонент из 2)"]),
                ("сахар, соус (сахар, соль)", ["сахар — 1-й из 2"]),
                ("соус (сахар, соль), сахар", ["сахар — 2-й из 2", "сахар внутри «соус» (1-й компонент из 2)"]),
                ("вода, сорбит, сахар (сукралоза)", ["сахар — 3-й из 3", "подсластители: сорбит, сукралоз"]),
                ("вода, краситель сахарный колер IV, подсластитель сукралоза", ["без сахара в составе", "подсластители: сукралоз", "краситель"]),
                ("вода питьевая, диоксид углерода, подсластители (аспартам, ацесульфам калия), консервант бензоат натрия (E211), ароматизатор",
                 ["без сахара в составе", "подсластители: аспартам, ацесульфам", "ароматизатор", "консервант", "E-добавки (1): E211"]),
                ("вода, пальмовое масло, крахмал, сорбат калия, глутамат натрия, краситель кармин, камедь ксантановая, ароматизатор, "
                 "Е330, E 211, e-322, Е1422, E160a",
                 ["без сахара в составе", "пальмовое масло", "ароматизатор", "крахмал", "консервант", "усилитель вкуса", "краситель",
                  "загуститель", "E-добавки (4): E1422 E160A E211 E330"]),
                ("", []), (None, [])):
            self.assertEqual(composition.flags(text), facts, text)

    def test_given_ingredients(self):
        self.assertEqual(composition.flags("что угодно", ["сахар", "вода"]), ["сахар — 1-й из 2"])


class NutritionTests(unittest.TestCase):
    def test_from_text(self):
        for text, n in (
                ("Пищевая ценность на 100 г: белки 3 г, жиры 3,2 г, углеводы 4,7 г, в т.ч. сахара 4,7 г; энергетическая ценность 58 ккал",
                 {"kcal": 58.0, "protein": 3.0, "fat": 3.2, "carbs": 4.7, "sugar": 4.7}),
                ("белки 0 г, жиры 0 г, углеводы 12 г,, в том числе сахара (общие) - 12 г, в том числе добавленный сахар - 12 г; 48 ккал",
                 {"kcal": 48.0, "protein": 0.0, "fat": 0.0, "carbs": 12.0, "sugar": 12.0, "added_sugar": 12.0}),
                ("энергетическая ценность 230, белки: 5", {"kcal": 230.0, "protein": 5.0}),
                ("", {}), (None, {})):
            self.assertEqual(composition.nutrition_from_text(text), n, text)

    def test_line(self):
        for n, line in ((None, ""), ({}, ""),
                        ({"kcal": 230, "protein": 3, "fat": 12, "carbs": 25, "sugar": 20, "added_sugar": 5},
                         "на 100 г: 230 ккал, Б 3, Ж 12, У 25, сахара 20 (добавленного 5)"),
                        ({"carbs": 10.6, "kcal": 42}, "на 100 г: 42 ккал, У 10.6, сахара ≤10.6 (сайт не пишет, не больше углеводов)"),
                        ({"sugar": 4}, "на 100 г: сахара 4"), ({"protein": 1}, "на 100 г: Б 1")):
            self.assertEqual(composition.nutrition_line(n), line, n)


class DescribeTests(unittest.TestCase):
    def test_lines(self):
        for args, lines in (
                ((None,), ["состав: сайт не указывает"]),
                (("", None, "Без сахара: Да"), ["состав: сайт не указывает", "о составе: Без сахара: Да"]),
                ((None, {"kcal": 40}), ["на 100 г: 40 ккал"]),
                ((".", None), ["состав (0): "]),
                (("Состав: вода, сахар. Сок не менее 10%. Может содержать следы молока.", {"kcal": 40}, "Сок: 10%"),
                 ["состав (2): 1) вода; 2) сахар", "в составе отмечено: Сок не менее 10%", "по составу: сахар — 2-й из 2",
                  "аллергены-следы: Может содержать следы молока", "о составе: Сок: 10%", "на 100 г: 40 ккал"])):
            self.assertEqual(composition.describe(*args), lines, args)


if __name__ == "__main__":
    unittest.main()
