import streamlit as st
import google.generativeai as genai
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import simpleSplit
from io import BytesIO
import os
import logging
import requests
import folium
from streamlit_folium import folium_static
from geopy.distance import geodesic
import json
from streamlit_js_eval import streamlit_js_eval

# Set up logging
logging.basicConfig(level=logging.INFO)

# Set up Gemini API
os.environ['GOOGLE_API_KEY'] = 'YOUR_API_KEY'  # Replace with your actual API key
genai.configure(api_key=os.environ['GOOGLE_API_KEY'])

# Initialize session state at the very beginning
if 'address' not in st.session_state:
    st.session_state['address'] = ""
if 'coordinates' not in st.session_state:
    st.session_state['coordinates'] = None

def get_current_location():
    """Get current location and convert to address"""
    js_code = """
    new Promise((resolve, reject) => {
        if (!navigator.geolocation) {
            reject('Geolocation is not supported');
            return;
        }
        navigator.geolocation.getCurrentPosition(
            (position) => {
                fetch(`https://nominatim.openstreetmap.org/reverse?lat=${position.coords.latitude}&lon=${position.coords.longitude}&format=json`)
                .then(response => response.json())
                .then(data => {
                    const result = JSON.stringify({
                        'address': data.display_name,
                        'lat': position.coords.latitude,
                        'lon': position.coords.longitude
                    });
                    resolve(result);
                })
                .catch(error => reject(error));
            },
            (error) => {
                reject(error);
            }
        );
    });
    """
    try:
        result = streamlit_js_eval(js_expressions=js_code, key='geolocation')
        if result:
            return json.loads(result)
    except Exception as e:
        st.error(f"Error getting location: {str(e)}")
    return None

def query_healthcare_assistant(symptoms):
    prompt = f"""Given the following symptoms: {symptoms}, list possible conditions and advice.
    Format the response as follows:
    Conditions:
    - condition 1
    - condition 2
    ...
    Advice:
    1. Step 1
    2. Step 2
    ...
    """
    model = genai.GenerativeModel('gemini-pro')
    try:
        response = model.generate_content(prompt)
        if response and response.parts:
            return response.text.strip()
        else:
            logging.error("No response parts found.")
            return "Sorry, there was an error generating the response."
    except Exception as e:
        logging.error(f"An error occurred: {e}")
        return "Sorry, there was an error generating the response."

def create_pdf(report):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    margin = 50

    c.setFont("Helvetica-Bold", 20)
    c.setFillColorRGB(0.2, 0.4, 0.6)
    c.drawString(margin, height - margin, "Healthcare Report")
    
    c.setFont("Helvetica", 12)
    c.setFillColorRGB(0, 0, 0)
    
    y = height - margin - 30
    max_width = width - 2 * margin

    def draw_wrapped_text(c, text, x, y, max_width, font_name="Helvetica", font_size=12):
        lines = simpleSplit(text, font_name, font_size, max_width)
        for line in lines:
            if y < margin:
                c.showPage()
                c.setFont(font_name, font_size)
                y = height - margin
            c.drawString(x, y, line)
            y -= font_size + 2

        return y

    for line in report.split('\n'):
        if line.strip():
            if line.startswith('Conditions:'):
                c.setFont("Helvetica-Bold", 16)
                c.setFillColorRGB(0.4, 0.6, 0.8)
                y = draw_wrapped_text(c, line, margin, y, max_width, "Helvetica-Bold", 16)
                c.setFont("Helvetica", 12)
                c.setFillColorRGB(0, 0, 0)
            elif line.startswith('Advice:'):
                c.setFont("Helvetica-Bold", 16)
                c.setFillColorRGB(0.4, 0.6, 0.8)
                y = draw_wrapped_text(c, line, margin, y, max_width, "Helvetica-Bold", 16)
                c.setFont("Helvetica", 12)
                c.setFillColorRGB(0, 0, 0)
            else:
                y = draw_wrapped_text(c, line, margin + 20, y, max_width - 20)

    c.save()
    buffer.seek(0)
    return buffer

def get_coordinates(address):
    url = f"https://nominatim.openstreetmap.org/search?q={address}&format=json&limit=1"
    headers = {"User-Agent": "HealthcareAssistant/1.0"}
    
    response = requests.get(url, headers=headers)
    data = response.json()
    
    if data:
        return float(data[0]['lat']), float(data[0]['lon'])
    
    return None, None

def find_nearby_places(lat, lon, place_type, radius=5000):
    overpass_url = "http://overpass-api.de/api/interpreter"
    
    overpass_query = f"""
    [out:json];
    node["amenity"="{place_type}"](around:{radius},{lat},{lon});
    way["amenity"="{place_type}"](around:{radius},{lat},{lon});
    relation["amenity"="{place_type}"](around:{radius},{lat},{lon});
    out center;
    """
    
    response = requests.get(overpass_url, params={'data': overpass_query})
    
    data = response.json()
    
    return data['elements']

st.set_page_config(page_title="Healthcare Assistant", layout="wide")
st.title("Clinical Prescription Chatbot")

symptoms = st.text_area("Describe your symptoms", "")

# Update just the location input section
col1, col2 = st.columns([3,1])

with col1:
    address = st.text_input("Enter your location:", key="location_input", value=st.session_state['address'])
    
with col2:
    if st.button("📍 Use My Location"):
        with st.spinner("Getting your location..."):
            location_data = get_current_location()
            if location_data and isinstance(location_data, dict):
                st.session_state['address'] = location_data.get('address', '')
                st.session_state['coordinates'] = [
                    location_data.get('lat'),
                    location_data.get('lon')
                ]
                # Update the address input with current location.
                st.experimental_set_query_params(location_input=st.session_state['address'])
                st.success("Location found!")
                st.info(f"📍 Your Current Location: {st.session_state['address']}")
                
search_radius = st.slider("Search radius for nearby facilities (km)", 1, 20, 5) * 1000 # Convert to meters

if st.button("Analyze Symptoms and Find Nearby Facilities"):
    
   if symptoms and address:
       with st.spinner("Analyzing your symptoms and finding nearby facilities..."):
           # Symptom analysis
           report = query_healthcare_assistant(symptoms)

           # Get coordinates and find nearby facilities.
           lat , lon= get_coordinates(address)

           if lat and lon:
               hospitals = find_nearby_places(lat , lon , "hospital" , search_radius )
               pharmacies= find_nearby_places(lat , lon , "pharmacy" , search_radius )

               # Display symptom analysis 
               st.subheader("Symptom Analysis")
               st.write(report)

               # Offer PDF download 
               pdf=create_pdf(report)

               st.download_button(
                   label="Download Report as PDF",
                   data=pdf,
                   file_name="healthcare_report.pdf",
                   mime="application/pdf"
               )

               # Display map 
               st.subheader("Nearby Healthcare Facilities")
               m= folium.Map(location=[lat , lon], zoom_start=13)

               folium.Marker([lat , lon], popup="Your Location",
                             icon=folium.Icon(color='red')).add_to(m)

               for hospital in hospitals:
                   if 'lat' in hospital :
                       folium.Marker(
                           [hospital['lat'], hospital['lon']],
                           popup=hospital.get('tags', {}).get('name', 'Hospital'),
                           icon=folium.Icon(color='blue', icon='plus-sign')
                       ).add_to(m)

               for pharmacy in pharmacies:
                   if 'lat' in pharmacy :
                       folium.Marker(
                           [pharmacy['lat'], pharmacy['lon']],
                           popup=pharmacy.get('tags', {}).get('name', 'Pharmacy'),
                           icon=folium.Icon(color='green', icon='medkit')
                       ).add_to(m)

               folium_static(m)

               # Display nearby facilities 
               col1 , col2=st.columns(2)

               with col1:
                   st.subheader("Nearby Hospitals:")
                   for hospital in hospitals[:5]: # Limit to top 5 results 
                       if 'tags' in hospital and 'name' in hospital['tags']:
                           distance=geodesic((lat , lon), (hospital['lat'], hospital['lon'])).km 
                           with st.container():
                               col_info,col_nav=st.columns([3 ,1])
                               with col_info:
                                   st.write(f"🏥 {hospital['tags']['name']}")
                                   st.write(f"📍 Distance: {distance:.2f} km")
                               with col_nav:
                                   maps_url=f"https://www.google.com/maps/dir/?api=1&origin={lat},{lon}&destination={hospital['lat']},{hospital['lon']}&travelmode=driving"
                                   st.markdown(f"🚗 Navigate", unsafe_allow_html=True)

                   st.divider()

               with col2:
                   st.subheader("Nearby Pharmacies:")
                   for pharmacy in pharmacies[:5]: # Limit to top 5 results 
                       if 'tags' in pharmacy and 'name' in pharmacy['tags']:
                           distance=geodesic((lat , lon), (pharmacy['lat'], pharmacy['lon'])).km 
                           with st.container():
                               col_info,col_nav=st.columns([3 ,1])
                               with col_info:
                                   st.write(f"💊 {pharmacy['tags']['name']}")
                                   st.write(f"📍 Distance: {distance:.2f} km")
                               with col_nav:
                                   maps_url=f"https://www.google.com/maps/dir/?api=1&origin={lat},{lon}&destination={pharmacy['lat']},{pharmacy['lon']}&travelmode=driving"
                                   st.markdown(f"🚗 Navigate", unsafe_allow_html=True)

                   st.divider()
           else:
               st.error("Unable to find coordinates for the given address. Please try again.")
   else:
       st.warning("Please enter both your symptoms and location.")

st.sidebar.markdown("""
## How to use:

1. Describe your symptoms in the text area.
2. Enter your location in the input field.
3. Adjust the search radius for nearby facilities using the slider.
4. Click 'Analyze Symptoms and Find Nearby Facilities' to get:

- A symptom analysis report
- A map of nearby hospitals and pharmacies
- Lists of the closest healthcare facilities

5. Download the symptom analysis report as a PDF if desired.
""")

st.markdown("---")
st.write("This app uses Gemini AI for symptom analysis and OpenStreetMap data to find nearby healthcare facilities.")
