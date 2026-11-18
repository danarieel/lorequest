"""Fake model answers for the generator tests: valid JSON objects for the 'frame' and for each scene."""
import json


def frame(req) -> dict:
    ru = req.language == "ru"
    return {
        "title": "Тайна старого маяка" if ru else "The Last Light",
        "narrator_name": "Смотритель" if ru else "The Keeper",
        "voice": ("Говорит спокойно и устало, с сухим юмором, никогда не шутит над бедой." if ru else
                  "Speaks calmly and wearily, with dry wit, and never jokes about real danger."),
        "outline": [(f"Сцена {i}: герой делает шаг вперёд." if ru else f"Scene {i}: the hero takes a step forward.")
                    for i in range(1, req.scenes + 1)],
        "fewshot": [
            {"choice": "Зажечь лампу" if ru else "Light the lamp",
             "reply": f"Смелый шаг, {req.hero}." if ru else f"A bold step, {req.hero}."},
            {"choice": "Спуститься вниз" if ru else "Go downstairs",
             "reply": f"{req.hero}, там темно." if ru else f"It is dark down there, {req.hero}."},
        ],
        "final_text": ("Свет снова горит, корабли находят дорогу, и история заканчивается тихо." if ru else
                       "The light burns again, ships find their way, and the story ends quietly."),
    }


def scene(req, i: int) -> dict:
    ru, last = req.language == "ru", i == req.scenes
    return {
        "title": f"Сцена {i}" if ru else f"Scene {i}",
        "body": (f"Ветер бьётся в окна, а {req.hero} стоит посреди комнаты и слушает, как скрипит старая лестница." if ru else
                 f"The wind beats at the windows while {req.hero} stands in the middle of the room, listening to the stairs creak."),
        "question": "Что делать дальше?" if ru else "What do you do next?",
        "options": ([f"Открыть дверь {i}", f"Заглянуть в окно {i}", f"Позвать на помощь {i}"] if ru else
                    [f"Open door {i}", f"Look through window {i}", f"Call for help {i}"]),
        "custom_label": "Свой вариант" if ru else "Your own plan",
        "custom_prompt": f"Опиши свой план, {req.hero}." if ru else f"Describe your plan, {req.hero}.",
        "context": "Тёмная комната старого маяка, шторм за окнами, скрипит лестница." if ru else
                   "A dark room in an old lighthouse, a storm outside, a creaking staircase.",
        "instruction": "Отреагируй коротко и мрачно." if ru else "React briefly and gravely.",
        "fallback": f"Рассказчик кивает, {req.hero}. Шторм это запомнит." if ru else
                    f"The narrator nods, {req.hero}. The storm will remember this.",
        "bridge_premise": "" if last else ("герой оказывается в нижней комнате маяка" if ru else
                                          "the hero ends up in the lower room of the lighthouse"),
        "image_prompt": f"A stormy lighthouse interior, scene {i}, cinematic lighting, no text",
    }


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


class FakeLLM:
    """Stands in for lorequest.llm.LLM: answers chat_json from a script and records every call.

    `script` is a list of raw strings (or dicts); when it runs out, valid frame/scene answers are produced.
    """

    def __init__(self, req, script=None):
        self.req, self.script, self.calls = req, list(script or []), []
        self._scene_no = 0

    async def chat_json(self, system, messages, schema, temperature=0.7, **_):
        self.calls.append({"system": system, "messages": [dict(m) for m in messages], "schema": schema})
        if self.script:
            item = self.script.pop(0)
            return item if isinstance(item, str) else dumps(item)
        if "outline" in schema.get("properties", {}):
            return dumps(frame(self.req))
        self._scene_no += 1
        return dumps(scene(self.req, self._scene_no))
