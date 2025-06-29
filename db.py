import getpass
import sys
from datetime import datetime

import oracledb


def connect_to_db(user, password, dsn):
    return oracledb.connect(user=user, password=password, dsn=dsn)


def get_locations(cursor):
    cursor.execute("""
        SELECT L.NAME, L.LOCATIONID FROM LOCATION L ORDER BY L.LOCATIONID ASC
    """)
    return cursor.fetchall()


def get_available_strandkoerbe(cursor, location_id, begin_date, end_date):
    cursor.execute("""
        SELECT S.KORBNR, S.KORBNAME, S.LOCATION_LOCATIONID
        FROM STRANDKORB S
        WHERE S.LOCATION_LOCATIONID = :location_id
        AND NOT EXISTS (
            SELECT * FROM RESERVIERUNG R
            WHERE R.STRANDKORB_KORBNR = S.KORBNR
              AND (
                  :begin_date BETWEEN R.BEGIN_DATETIME AND R.END_DATETIME
                  OR :end_date BETWEEN R.BEGIN_DATETIME AND R.END_DATETIME
                  OR  R.BEGIN_DATETIME BETWEEN :begin_date AND :end_date
                  OR R.END_DATETIME BETWEEN :begin_date AND :end_date
              ))
    """, {
        "location_id": location_id,
        "begin_date": begin_date,
        "end_date": end_date
    })
    return cursor.fetchall()


def get_services_for_strandkorb(cursor, korb_nr, location_id):
    cursor.execute("""
        SELECT STC.STRANDKORB_KORBNR, STC.SERVICES_SERVICEID
        FROM SERVICETOCHAIR STC
        INNER JOIN SERVICES S ON S.SERVICEID = STC.SERVICES_SERVICEID
        WHERE STC.STRANDKORB_KORBNR = :korb_nr  AND STC.Strandkorb_Location_locationID = :location_id
    """, {"korb_nr": korb_nr, "location_id": location_id})
    return cursor.fetchall()


def check_volleyball_tournament(cursor, begin_date, end_date):
    cursor.execute("""
        SELECT 1
        FROM VOLLEYBALLTURNIER V
        WHERE :begin_date BETWEEN V.BEGIN_DATETIME AND V.END_DATETIME
        OR :end_date BETWEEN V.BEGIN_DATETIME AND V.END_DATETIME
    """, {"begin_date": begin_date, "end_date": end_date})
    return cursor.fetchone() is not None


def is_strandkorb_available(cursor, korb_nr, location_id, begin_date, end_date):
    cursor.execute("""
        SELECT S.KORBNR
        FROM STRANDKORB S
        WHERE S.KORBNR = :korb_nr AND S.LOCATION_LOCATIONID = :location_id
        AND NOT EXISTS (
            SELECT 1
            FROM RESERVIERUNG R
            WHERE R.STRANDKORB_KORBNR = S.KORBNR
              AND R.STRANDKORB_LOCATION_LOCATIONID = S.LOCATION_LOCATIONID
              AND (
                    :begin_date BETWEEN R.BEGIN_DATETIME AND R.END_DATETIME
                  OR :end_date BETWEEN R.BEGIN_DATETIME AND R.END_DATETIME
                  OR  R.BEGIN_DATETIME BETWEEN :begin_date AND :end_date
                  OR R.END_DATETIME BETWEEN :begin_date AND :end_date
              )
        )
    """, {
        "korb_nr": korb_nr,
        "location_id": location_id,
        "begin_date": begin_date,
        "end_date": end_date
    })
    return cursor.fetchone() is not None


def create_reservation(cursor, student_id, korb_nr, location_id, begin_date, end_date):
    cursor.execute("""
        INSERT INTO RESERVIERUNG (
            STUDENT_STUDENTID, STRANDKORB_KORBNR, BEGIN_DATETIME, END_DATETIME, STRANDKORB_LOCATION_LOCATIONID
        ) VALUES (
            :student_id, :korb_nr, :begin_date, :end_date, :location_id
        )
    """, {
        "student_id": student_id,
        "korb_nr": korb_nr,
        "begin_date": begin_date,
        "end_date": end_date,
        "location_id": location_id
    })


def add_services_to_reservation(cursor, korb_nr, location_id, student_id, reservation_id, service_ids):
    for sid in service_ids:
        cursor.execute("""
            INSERT INTO SERVICETORESERVATION VALUES (:korb_nr, :location_id, :service_ids, :student_id, :reservation_id)
        """, {
            "korb_nr": korb_nr,
            "location_id": location_id,
            "service_ids": sid,
            "student_id": student_id,
            "reservation_id": reservation_id
        })


def unlock_strandkorb_after_reservation(connection):
    connection.commit()


def is_within_usage_period(cursor, reservation_id, check_date):
    cursor.execute("""
        SELECT 1
        FROM RESERVIERUNG
        WHERE RID = :reservation_id
          AND BEGIN_DATETIME <= :check_date
          AND :check_date <= END_DATETIME
    """, {"reservation_id": reservation_id, "check_date": check_date})
    return cursor.fetchone() is not None


def update_statistics_after_usage(cursor, reservation_id, stunden_dif):
    cursor.execute("""
        UPDATE WARTUNG
        SET NUTZUNGEN = NUTZUNGEN + 1,
            STUNDENANZAHL = STUNDENANZAHL + :stunden_dif
        WHERE STRANDKORB_KORBNR = (
            SELECT STRANDKORB_KORBNR FROM RESERVIERUNG WHERE RID = :reservation_id
        )
        AND STRANDKORB_LOCATION_LOCATIONID = (
            SELECT STRANDKORB_LOCATION_LOCATIONID FROM RESERVIERUNG WHERE RID = :reservation_id
        )
    """, {"reservation_id": reservation_id, "stunden_dif": stunden_dif})


def get_services_used(cursor, reservation_id):
    cursor.execute("""
        SELECT SERVICES_SERVICEID FROM SERVICETOCHAIR
        WHERE STRANDKORB_KORBNR = (
            SELECT STRANDKORB_KORBNR FROM RESERVIERUNG WHERE RID = :reservation_id
        )
        AND STRANDKORB_LOCATION_LOCATIONID = (
            SELECT STRANDKORB_LOCATION_LOCATIONID FROM RESERVIERUNG WHERE RID = :reservation_id
        )
    """, {"reservation_id": reservation_id})
    return cursor.fetchall()


def get_service_payment_status(cursor, reservation_id):
    cursor.execute("""
        SELECT S.BEZAHLT, S.PREIS, STR.SERVICETOCHAIR_SERVICEID
        FROM SERVICETORESERVATION STR
        INNER JOIN SERVICES S ON S.SERVICEID = STR.SERVICETOCHAIR_SERVICEID
        WHERE RESERVIERUNG_RID = :reservation_id
    """, {"reservation_id": reservation_id})
    return cursor.fetchall()


def prompt_input(prompt_text, allow_exit=True):
    val = input(prompt_text).strip()
    if allow_exit and val.lower() in {"exit", "quit"}:
        print("Programm beendet.")
        sys.exit()
    return val

def print_service_and_drink_prices(cursor, reservation_id):
    print("\n🧾 Servicebezahlung und Preise:")
    total_price = 0.0

    # ➤ 1. Servicepreise (aus normalen Services)
    for bezahlt, preis, serviceid in get_service_payment_status(cursor, reservation_id):
        status = "Bezahlt" if bezahlt else "Offen"
        print(f"Service {serviceid}: {status}, Preis: {preis}€")
        total_price += preis

    # ➤ 2. Getränkepreise (aus DrinksToReservation, verknüpft mit Service)
    cursor.execute("""
        SELECT DTR.Amount, S.Preis, DTR.Drink_ServiceID
        FROM Drinkstoreservation DTR
        JOIN services S ON DTR.Drink_ServiceID = S.ServiceID
        WHERE DTR.Reservierung_RID = :rid
    """, {"rid": reservation_id})

    drink_entries = cursor.fetchall()
    for amount, preis_pro_stück, serviceid in drink_entries:
        gesamtpreis = amount * preis_pro_stück
        print(f"Getränk-Service {serviceid}: {amount} × {preis_pro_stück}€ = {gesamtpreis}€")
        total_price += gesamtpreis

    print(f"\n💰 Gesamtpreis (inkl. Getränke): {total_price:.2f}€")


def get_student_id_for_reservation(cursor, reservation_id):
    cursor.execute("SELECT STUDENT_STUDENTID FROM RESERVIERUNG WHERE RID = :rid", {"rid": reservation_id})
    result = cursor.fetchone()
    return result[0] if result else None

def handle_usage_flow():
    reservation_id = int(prompt_input("Reservierungs-ID: "))
    unlock_strandkorb_after_reservation(connection)

    check_date = datetime.strptime(prompt_input("Datum der Nutzung überprüfen (YYYY-MM-DD): "), "%Y-%m-%d")
    if is_within_usage_period(cursor, reservation_id, check_date):
        print("✅ Zugriff erlaubt - innerhalb der Reservierung.")

        # Get korb_nr and location_id from reservation
        cursor.execute("""
            SELECT STRANDKORB_KORBNR, STRANDKORB_LOCATION_LOCATIONID 
            FROM RESERVIERUNG 
            WHERE RID = :rid
        """, {"rid": reservation_id})
        korb_data = cursor.fetchone()
        if not korb_data:
            print("❌ Reservierung nicht gefunden.")
            return
        korb_nr, location_id = korb_data

        while True:
            print("\n3: Reservierung beenden")
            print("4: Service dazubuchen")
            print("5: Drinks")
            sub_choice = prompt_input("Auswahl: ").strip()

            if sub_choice == "3":
                stunden = float(prompt_input("Wie viele Stunden wurde genutzt? "))
                update_statistics_after_usage(cursor, reservation_id, stunden)
                print("📊 Statistik aktualisiert.")
                print_service_and_drink_prices(cursor, reservation_id)
                break

            elif sub_choice == "4":
                # Show already booked services
                booked_service_ids = {sid[0] for sid in get_services_used(cursor, reservation_id)}
                print("\nBereits gebuchte Services:")
                if booked_service_ids:
                    for sid in booked_service_ids:
                        print(f"Service-ID: {sid}")
                else:
                    print("Keine gebuchten Services.")

                # Show all available services and determine unbooked
                available_services = get_services_for_strandkorb(cursor, korb_nr, location_id)
                unbooked_services = [row for row in available_services if row[1] not in booked_service_ids]

                print("\nVerfügbare (noch nicht gebuchte) Services:")
                if unbooked_services:
                    for row in unbooked_services:
                        print(f"ServiceID: {row[1]}")
                else:
                    print("⚠️ Keine neuen Services verfügbar.")

                # Prompt regardless of availability
                service_ids_input = prompt_input(
                    "Neue ServiceIDs auswählen (mit Komma trennen oder leer lassen zum Überspringen): ",
                    allow_exit=False)
                if service_ids_input:
                    try:
                        service_ids = [int(sid.strip()) for sid in service_ids_input.split(",") if sid.strip()]
                        student_id = get_student_id_for_reservation(cursor, reservation_id)
                        add_services_to_reservation(cursor, korb_nr, location_id, student_id, reservation_id, service_ids)
                        print("✅ Services hinzugefügt.")
                    except ValueError:
                        print("❌ Ungültige Eingabe – bitte nur Zahlen verwenden.")
                else:
                    print("ℹ️ Keine Services ausgewählt.")

            elif sub_choice == "5":
                print("\n🥤 Verfügbare Getränke:")
                cursor.execute("SELECT ServiceID, DrinkName FROM Drink ORDER BY DrinkName")
                drinks = cursor.fetchall()

                if not drinks:
                    print("⚠️ Keine Getränke vorhanden.")
                    continue

                drink_map = {str(i + 1): (drink[0], drink[1]) for i, drink in enumerate(drinks)}
                for i, (sid, name) in enumerate(drinks, start=1):
                    print(f"{i}: {name}")

                student_id = get_student_id_for_reservation(cursor, reservation_id)
                selected_drinks = []

                while True:
                    drink_choice = prompt_input("Wähle eine Getränkenummer (oder 'fertig' zum Beenden): ").strip()
                    if drink_choice.lower() == "fertig":
                        break
                    if drink_choice not in drink_map:
                        print("❌ Ungültige Auswahl.")
                        continue

                    try:
                        amount = int(prompt_input(f"Wieviele Stück von {drink_map[drink_choice][1]}? "))
                        if amount <= 0:
                            print("⚠️ Anzahl muss positiv sein.")
                            continue
                        selected_drinks.append((
                            student_id,
                            reservation_id,
                            drink_map[drink_choice][0],
                            amount
                        ))
                    except ValueError:
                        print("❌ Bitte eine gültige Zahl eingeben.")

                if selected_drinks:
                    for sid, rid, drink_sid, qty in selected_drinks:
                        cursor.execute("""
                            INSERT INTO DrinksToReservation (
                                Reservierung_studentID, Reservierung_RID, Drink_ServiceID, Amount
                            )
                            VALUES (:sid, :rid, :dsid, :amt)
                        """, {
                            "sid": sid,
                            "rid": rid,
                            "dsid": drink_sid,
                            "amt": qty
                        })
                    print("✅ Getränke zur Reservierung hinzugefügt.")
                else:
                    print("ℹ️ Keine Getränke ausgewählt.")

            else:
                print("❌ Ungültige Auswahl.")
    else:
        print("🔒 Zugriff verweigert - außerhalb der Reservierung.")



def handle_reservation_flow():
    print("\nVerfügbare Standorte:")
    locations = get_locations(cursor)
    for name, loc_id in locations:
        print(f"{loc_id}: {name}")

    location_id = int(prompt_input("Wähle Standort-ID: "))
    begin_date = datetime.strptime(prompt_input("Buchung Beginn (YYYY-MM-DD): "), "%Y-%m-%d")
    end_date = datetime.strptime(prompt_input("Buchung Ende (YYYY-MM-DD): "), "%Y-%m-%d")

    print("\nVerfügbare Strandkörbe:")
    available_chairs = get_available_strandkoerbe(cursor, location_id, begin_date, end_date)
    if not available_chairs:
        print("⚠️ Keine Strandkörbe verfügbar.")
        return
    for korb in available_chairs:
        print(korb)

    korb_nr = int(prompt_input("Wähle Korb-Nr: "))
    student_id = int(prompt_input("Studenten-ID eingeben: "))

    if check_volleyball_tournament(cursor, begin_date, end_date):
        print("⚠️ Volleyballturnier während des gewählten Zeitraums!")
    else:
        print("✅ Kein Turnierkonflikt.")

    connection.autocommit = False
    try:
        cursor.execute("LOCK TABLE RESERVIERUNG IN EXCLUSIVE MODE")

        if not is_strandkorb_available(cursor, korb_nr, location_id, begin_date, end_date):
            print("❌ Strandkorb nicht verfügbar.")
            connection.rollback()
        else:
            print("✅ Strandkorb ist verfügbar.")
            create_reservation(cursor, student_id, korb_nr, location_id, begin_date, end_date)
            connection.commit()
            print("✅ Reservierung erfolgreich.")

            cursor.execute("SELECT MAX(RID) FROM RESERVIERUNG WHERE STUDENT_STUDENTID = :id", {"id": student_id})
            reservation_id = cursor.fetchone()[0]

            services = get_services_for_strandkorb(cursor, korb_nr, location_id)
            if services:
                print("\nVerfügbare Services:")
                for row in services:
                    print(f"ServiceID: {row[1]}")
                service_ids_input = prompt_input(
                    "ServiceIDs auswählen (mit Komma trennen oder leer lassen zum Überspringen): ", allow_exit=False)
                if service_ids_input:
                    service_ids = [int(sid.strip()) for sid in service_ids_input.split(",") if sid.strip()]
                    add_services_to_reservation(cursor, korb_nr, location_id, student_id, reservation_id, service_ids)

            unlock_strandkorb_after_reservation(connection)
            print("✅ Reservierung abgeschlossen und Services gespeichert.")
    except Exception as e:
        print(f"❌ Fehler bei der Reservierung: {e}")
        connection.rollback()
    finally:
        connection.autocommit = True


def main():
    global cursor, connection
    dsn = oracledb.makedsn("teddy.it.fh-salzburg.ac.at", 1521, sid="ORCLCDB")

    while True:
        print("\n--- Neues Buchungssystem gestartet ---")
        user = prompt_input("Benutzername (oder 'exit'): ")
        if user.lower() == "exit":
            break
        password = getpass.getpass("Passwort: ")

        try:
            connection = connect_to_db(user, password, dsn)
            cursor = connection.cursor()
            connection.autocommit = True

            while True:
                print("\n1: Reservierung")
                print("2: Freischaltung & Nutzung")
                print("exit: Programm beenden")
                choice = prompt_input("Auswahl treffen (1, 2 oder 'exit'): ").strip().lower()

                if choice == "1":
                    handle_reservation_flow()
                elif choice == "2":
                    handle_usage_flow()
                elif choice == "exit":
                    print("Programm beendet.")
                    return
                else:
                    print("❌ Ungültige Auswahl.")

        except Exception as e:
            print(f"⚠️ Fehler: {e}")
            if connection:
                connection.rollback()
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()


if __name__ == "__main__":
    main()
