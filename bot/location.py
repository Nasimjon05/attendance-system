import math

def haversine_distance(lat1, lng1, lat2, lng2):
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def is_within_radius(classroom_lat, classroom_lng, student_lat, student_lng, radius_meters):
    distance = haversine_distance(classroom_lat, classroom_lng, student_lat, student_lng)
    return distance <= radius_meters, distance
