"""
Smoke test two registered operators with separate weather and body-temperature tools.

The script creates random city/weather and Celsius-temperature cases, asks the
agent to use both operators in one session, verifies both operator methods ran
with expected values, then deletes the deterministic test session.
"""
import asyncio
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
from dynamic_agent_client import DynamicAgentClient, AgentOperator, agent_tool, description, flow
from dynamic_agent_client.service_handler import ServiceHandler
from dynamic_agent_service.external_service.pg_instance import PgInstance
from dynamic_agent_service.external_service.redis_instance import RedisInstance
from dynamic_agent_service.service.session_accessor import SessionAccessor

load_dotenv()


SESSION_ID = "smoke-two-operator"


class CityWeatherOperator(AgentOperator):

    def __init__(self, reports: dict[str, dict]):
        self.reports = reports
        self.probe_calls = []
        super().__init__()

    @description
    def weather_description(self) -> str:
        return "A city weather operator that lists supported cities and returns weather reports."

    @flow
    def weather_flow(self) -> str:
        return "Call available_cities before requesting a report, then call weather_report for a selected city."

    @agent_tool(description="List cities with available weather reports")
    def available_cities(self) -> list[str]:
        result = sorted(self.reports.keys())
        self.probe_calls.append({"tool": "available_cities", "result": result})
        return result

    @agent_tool(description="Return a weather report for a city")
    def weather_report(self, city: str) -> dict:
        """
        :param city: The city name to fetch weather for
        """
        result = self.reports[city]
        self.probe_calls.append({"tool": "weather_report", "city": city, "result": result})
        return result


class BodyTemperatureOperator(AgentOperator):

    def __init__(self):
        self.probe_calls = []
        super().__init__()

    @description
    def body_temperature_description(self) -> str:
        return "A body temperature operator for converting Celsius readings and classifying fever level."

    @flow
    def body_temperature_flow(self) -> str:
        return "Use classify_temperature when a body temperature reading is provided."

    @agent_tool(description="Convert Celsius body temperature to Fahrenheit and classify fever level")
    def classify_temperature(self, celsius: float) -> dict:
        """
        :param celsius: Body temperature in degrees Celsius
        """
        fahrenheit = round(celsius * 9 / 5 + 32, 1)
        if celsius >= 38.0:
            status = "fever"
        elif celsius >= 37.3:
            status = "elevated"
        else:
            status = "normal"

        result = {"celsius": celsius, "fahrenheit": fahrenheit, "status": status}
        self.probe_calls.append({"tool": "classify_temperature", "result": result})
        return result


def build_weather_case() -> tuple[dict[str, dict], str]:
    rng = random.Random()
    cities = ["Austin", "Boston", "Chicago", "Denver", "Seattle"]
    conditions = ["clear", "rain", "fog", "wind", "snow"]
    reports = {}
    for city in cities:
        reports[city] = {
            "city": city,
            "temperature_c": rng.randint(-5, 36),
            "condition": rng.choice(conditions),
            "humidity_percent": rng.randint(20, 95),
        }
    return reports, rng.choice(cities)


def build_temperature_case() -> tuple[float, dict]:
    rng = random.Random()
    celsius = round(rng.uniform(36.1, 39.4), 1)
    fahrenheit = round(celsius * 9 / 5 + 32, 1)
    if celsius >= 38.0:
        status = "fever"
    elif celsius >= 37.3:
        status = "elevated"
    else:
        status = "normal"
    return celsius, {"celsius": celsius, "fahrenheit": fahrenheit, "status": status}


async def main():
    await PgInstance.initialize()
    await RedisInstance.initialize()

    client = None
    tool_calls = []

    try:
        await SessionAccessor.delete_session(SESSION_ID)

        weather_reports, target_city = build_weather_case()
        body_celsius, expected_temperature = build_temperature_case()
        expected_weather = weather_reports[target_city]

        print(f"target_city: {target_city}")
        print(f"expected_weather: {expected_weather}")
        print(f"body_celsius: {body_celsius}")
        print(f"expected_temperature: {expected_temperature}")

        port = os.getenv("PORT", "7777")
        await DynamicAgentClient.connect(server_addr=f"http://localhost:{port}")

        client = await DynamicAgentClient.create(
            setting=(
                "You are a concise assistant. Use the available tools for weather and "
                "body-temperature tasks. Do not invent weather or temperature calculations."
            ),
            session_id=SESSION_ID,
        )
        assert client.session_id == SESSION_ID
        assert client.messages == [], "fresh smoke session should start empty"

        client.on_tool_call(lambda tool_name, arguments: tool_calls.append((tool_name, arguments)))

        weather_operator = CityWeatherOperator(weather_reports)
        temperature_operator = BodyTemperatureOperator()
        weather_registration = await client.add_operator(weather_operator)
        temperature_registration = await client.add_operator(temperature_operator)
        print(f"weather registered: {weather_registration}")
        print(f"temperature registered: {temperature_registration}")

        response = await client.trigger(
            f"First list the available cities, then get the weather report for {target_city}. "
            f"Also classify this body temperature: {body_celsius} Celsius. "
            "Reply with only the city weather report and body temperature classification."
        )
        print(f"response: {response}")

        called_names = {name for name, _ in tool_calls}
        assert "CityWeatherOperator_available_cities" in called_names
        assert "CityWeatherOperator_weather_report" in called_names
        assert "BodyTemperatureOperator_classify_temperature" in called_names

        weather_tools = [call["tool"] for call in weather_operator.probe_calls]
        assert "available_cities" in weather_tools, "expected available_cities to execute"
        assert "weather_report" in weather_tools, "expected weather_report to execute"

        weather_report_call = next(call for call in weather_operator.probe_calls if call["tool"] == "weather_report")
        assert weather_report_call["city"] == target_city
        assert weather_report_call["result"] == expected_weather

        assert temperature_operator.probe_calls, "expected classify_temperature to execute"
        assert temperature_operator.probe_calls[0]["result"] == expected_temperature

        assert target_city in response
        assert expected_weather["condition"] in response
        assert str(expected_weather["temperature_c"]) in response
        assert str(expected_temperature["fahrenheit"]) in response
        assert expected_temperature["status"] in response.lower()

        print("ALL PASSED")
    finally:
        if client is not None:
            await client.close()

        await SessionAccessor.delete_session(SESSION_ID)
        await PgInstance.close()
        await RedisInstance.close()
        await ServiceHandler.stop()


if __name__ == "__main__":
    asyncio.run(main())
