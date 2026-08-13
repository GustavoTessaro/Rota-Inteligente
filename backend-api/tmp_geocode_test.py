from app.services.google_maps_service import GoogleMapsService

if __name__ == '__main__':
    g = GoogleMapsService()
    address = 'Rua Heitor Villa Lobos, 225, São Francisco, Lages, SC, 88506400, Brasil'
    print('Address to send:', address)
    res = g.geocode(address)
    import json
    print('Result:', json.dumps(res, ensure_ascii=False, indent=2))
