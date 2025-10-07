from flask import Flask, request  
from twilio.twiml.messaging_response import MessagingResponse  
import requests  
import logging   
import json      


app = Flask(__name__)

logging.basicConfig(level=logging.DEBUG)

# endpoint "/whatsapp" POST z Twilio
@app.route("/whatsapp", methods=["POST"])
def whatsapp_reply():
    incoming_msg = request.values.get("Body", "").strip()

    num_media = int(request.values.get("NumMedia", 0))

    resp = MessagingResponse()
    msg = resp.message()
# Sprawdzanie zawartosci wiadomosci i odpowiedz
    try:
        if num_media > 0:
            
            reply = "Przepraszam, nie mogę przetworzyć plików multimedialnych. Proszę, wyślij wiadomość tekstową."
        
        elif incoming_msg:
            
            logging.debug(f"Wiadomość od użytkownika (WhatsApp): {incoming_msg}")
            r = requests.post("http://127.0.0.1:4000/chat", json={"prompt": incoming_msg})

            if r.status_code == 200:
                try:
                    # Sparsowanie odpowiedźi jako JSON
                    data = r.json()
                except ValueError:
                    # Serwer zwrócił niepoprawny JSON
                    reply = "Błąd: serwer zwrócił niepoprawny format JSON."
                else:
                    
                    logging.debug(f"Odpowiedź z FastAPI: {data}")

                    # Jeśli w odpowiedzi jest pole "response" jako tekst
                    if "response" in data and isinstance(data["response"], str):
                        reply = data["response"]
                        reply = reply.replace('\n', ' ').replace('\r', ' ').strip().strip('"')
                    else:
                        # Jeśli otrzymano czysty obiekt JSON – formatujemy do tekstu
                        reply = json.dumps(data, ensure_ascii=False, indent=2)

            else:
                # Jeśli serwer zwrócił błąd HTTP (np. 500, 404 itp.)
                reply = f"Błąd: serwer zwrócił kod {r.status_code}"

        else:
            # Jeśli wiadomość jest pusta
            reply = "Wiadomość jest pusta."

    except Exception as e:
        # Obsługa innych błędów
        reply = f"Błąd podczas przetwarzania: {e}"

    # Logujemy i wysyłamy wiadomość zwrotną do użytkownika
    logging.debug(f"Wysyłamy do WhatsApp: {reply}")
    msg.body(reply)
    return str(resp)

# Uruchamiamy aplikację Flask na porcie 5000
if __name__ == "__main__":
    app.run(debug=True, port=5000)




