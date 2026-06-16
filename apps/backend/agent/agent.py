"""
    Experimenting with the designed tools for agent workflows.
"""
from agent.tools import search_recipes, get_recipe_details, search_discounts, get_discount_details
from agent.utils import load_config_openai
import asyncio
from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_core.models import ModelInfo
from autogen_agentchat.teams import SelectorGroupChat
from autogen_agentchat.conditions import MaxMessageTermination, TextMentionTermination
from autogen_agentchat.ui import Console

from db.session import init_engine

def agent_setup():
    config = load_config_openai()
    api_key = config[0].get("api_key")
    api_key = api_key.strip()

    model_client = OpenAIChatCompletionClient(
        model="gpt-4o-mini",
        #model="deepseek-chat",
        api_key=api_key,
        model_info=ModelInfo(vision=True, function_calling=True, json_output=True, family="unknown",
                             structured_output=True)
    )

    planning_agent = AssistantAgent(
        "PlanningAgent",
        description= """ Orchestrator Agent, der den Verlauf des Group-Chats durch die Auswahl der Agenten bestimmt.""",
        model_client=model_client,
        system_message=""" 
            Du bist mit der Planung beauftragt, den gegebenen Prompt zu erfüllen. Dafür sollst Du als selector 
            auswählen, welche Agenten in welcher Reihenfolge aufgerufen werden sollen um ihre jeweiligen Subaufgaben 
            zu erfüllen. Orientiere dich dabei an den Descriptions der einzelnen Agenten. Deine Sub-Agenten haben
            Zugriff auf Tools, um Rezepte und Angebote aus der DB Session abzufragen, also nutze Sie!
            Bei der Orchestrierung solltest Du folgende Schlagwörter beachten, mit denen die Agenten antworten:
            - "cook". Antwortet mit [REZEPTE], wenn ein Vorschlag von Rezepten ausgewählt oder angepasst wurde.
                Wenn der Cook am Zug war und nicht mit [REZEPTE] geantwortet hat, soll er die Suche mit einer höheren 
                Difficulty wiederholen.
            - "inspector": Antwortet mit [APPROVED], wenn die Menge der Rezepte ideal ist und keine Zutaten durch Zutaten
                im Angebot ersetzt werden können. Dann kannst Du den writer-Agent für die Generierung der Ausgabe verwenden.
            - "insepctor": Anwtwortet mit [SUGGESTED], wenn Zutaten durch andere Zutaten, die im Angebot sind, ersetzt
                wurden. Dann sollte der cook-Agent überprüfen, ob die ersetzten Zutaten passen. Der Koch kann die 
                Vorschläge teilweise oder vollständig übernehmen, aber auch vollständig ablehnen.
            - "writer": Antwortet mit [GENERATED] wenn er eine Konsolenausgabe als finale Ausgabe erzeugt hat. Diese solltest
                Du dann an den Nutzenden ausgeben.
            Du selbst solltest nach der Ausgabe der finalen Konsolenausgabe ausschließlich mit [TERMINATE] antworten.
            """,
    )

    # 1. Cook:
    cook = AssistantAgent(
        "cook",
        model_client=model_client,
        description= "Inspiziert die Gerichte aus der Datenbank und ordnet ein, ob diese für die Aufgabe geeignet sind.",
        tools=[search_recipes, get_recipe_details],
        system_message="""
                    Du bist ein Datenanalyst und wirst dazu verwendet, um eine Datenbank mit Kochrezepten auszulesen.
                    Du hast dafür zwei Tools zur Verfügung:
                    - "search_recipes": 
                        erlaubt dir anhand passender Funktionsargumente eine 
                        Übersicht der Rezepte aus der Datenbank abzufragen. Wenn die Rückgabe eine leere Liste ist,
                        solltest Du schrittweise die Funktionsargumente anpassen (z.B. erhöhen der Difficulty).
                    - "get_recipe_details": 
                        erlaubt dir anhand einer Rezept ID gezielt Details dieses Rezeptes abzufragen.
                        Wenn Du zu einer Rezept ID keine Informationen findest, schließe dieses Rezept aus und wähle
                        stattdessen die best mögliche Alternative.
                    Solltest Du nach mehreren Iterationen eine Auswahl der Rezepte getroffen haben, übergebe diese Menge 
                    von Rezepten dem Planungsagenten und antworte erneut mit [REZEPTE]. 
                """,
        )

    # 2. Analyst:
    inspector = AssistantAgent(
        "inspector",
        model_client=model_client,
        description="""Inspiziert, ob benötigte Zutaten im Angebot sind. Sollten Ersatzprodukte für Zutaten im Angebot sein,
                    werden diese ebenfalls ausgegeben.""",
        tools=[get_recipe_details, search_discounts, get_discount_details],
        system_message="""
                Du bist ein Datenanalyst und sollst überprüfen, ob Zutaten aus einer gegebenen Menge im Angebot sind 
                oder nicht. Sollte eine Zutat nicht im Angebot sein, aber ein mögliches Ersatzprodukt schon,
                dann suche für diese Zutaten das Angebot heraus und gebe diese ebenfalls aus.
                Du hast ein Tool zur Verfüfung:
                - "get_recipe_details":
                    erlaubt dir Anhand der übergebenen Rezept IDs diese aus der Datenbank abzufragen, um die Zutaten
                    zu erhalten.
                - "search_discounts":
                    erlaubt dir die Menge von benötigten Zutaten mit der Angebotsliste abzugleichen.
                Solltest Du keine Angebote oder Verbesserungen finden, antworte ausschließlich mit [APPROVED].
                Solltest Du hingegen Zutaten ersetzt habe, durch welche die im Angebot sind, dann antworte 
                ausschließlich mit [SUGGESTED].
            """
    )

    # 3. Writer:
    writer = AssistantAgent(
        "writer",
        model_client=model_client,
        description="Generiert eine übersichtliche Konsolen Ausgabe mit den ausgewähltn Rezepten und zugehörigen Zutaten.",
        system_message="""
                Du sollst eine übersichtliche Konsolenausgabe generieren, sodass alle ausgewählten Rezepte und ihre 
                benötigten Zutaten aufgelistet sind. Sollten davon Zutaten im Angebot sein oder durch Zutaten erstetzt 
                worden sein, schreibe dies hinter die Zutat mit dem anfallenden Rabatt. Übergebe deine Konsolenausgabe
                den Planungsagenten und antworte erneut ausschließlich mit [GENERATED].
                """
    )

    planner_termination = TextMentionTermination("[TERMINATE]")
    # Define max. messages
    max_msg_termination = MaxMessageTermination(max_messages=20)

    combined_termination =  planner_termination | max_msg_termination

    team = SelectorGroupChat(
        [planning_agent, cook, inspector, writer],
        model_client=model_client,
        termination_condition=combined_termination,
        # selector_prompt=selector_prompt,
        allow_repeated_speaker=True,
    )
    return team


async def main():
    print("Starte Datenbank-Verbindung...")
    init_engine()

    prompt = """.
            Bitte suche mir aus den Rezepten die drei Gerichte mit der geringsten Schwierigkeit heraus,
            wovon aber mindestens eins vegetarisch sein sollte.
            """

    # Setup Agents
    agent_team = agent_setup()
    await agent_team.reset()
    await Console(agent_team.run_stream(task=prompt))


if __name__ == "__main__":
    asyncio.run(main())
