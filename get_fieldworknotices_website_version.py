import requests
from tabulate import tabulate
import csv
from extract_and_scan import download_files
import os
import json

def read_csv(path_to_csv):
    with open(path_to_csv, 'r', newline='') as f:
            list_of_lists = [] #list to contain rows from the csv file
            for row in csv.reader(f, dialect='excel'):
                list_of_lists.append(row) # adding rows to the list
    return list_of_lists

def rank_order_counties(search_results_reader):
    counties_dict = {}
    for count, row in enumerate(search_results_reader):
        if count == 0: continue
        county = row[4]
        current_county_count = counties_dict.setdefault(county,0)
        counties_dict[county] = current_county_count + 1

    return sorted(counties_dict.items(), key=lambda x:x[1], reverse=True)

def main():
    print('This program gets the Field work notifications from the date range specified')
    input('Press Enter to Continue') 
    date_from = input("DATE FROM ex:08/08/2022 or 08-08-2022: ")
    date_from = date_from.replace("-","/")
    date_to = input("DATE TO ex:08/15/2022 or 08-15-2022: ")
    date_to = date_to.replace("-","/")
    url = "https://prodenv.dep.state.fl.us/DepNexus/public/electronic-documents"
    data = {
        "__checkbox_electronicDocument.airDivision": "true",
        "__checkbox_electronicDocument.waterDivision": "true",
        "__checkbox_electronicDocument.wasteDivision": "true",
        "electronicDocument.documentType": "FIELD WORK NOTIFICATION",
        "electronicDocument.dateFrom": date_from,
        "electronicDocument.dateTo": date_to,
        "electronicDocument.dateReceivedFrom":"", 
        "electronicDocument.dateReceivedTo": "",
        "electronicDocument.subject": "",
        "electronicDocument.facilityId": "",
        "electronicDocument.permitId": "",
        "electronicDocument.facilityDistrict": "",
        "electronicDocument.facilityCounty": "",
        "newSearch": "Yes",
        "electronicDocument.sortCriteria": ""
        }
    try:
        response = requests.post(url, data)
        cookies = response.cookies
        secondr = requests.get('https://prodenv.dep.state.fl.us/DepNexus/public/export!exportElectronicDocuments?wildCardMatch=true',
        cookies=cookies)

    except:
        #this is only run if the above try clause fails, then goes to the finally clause
        print("Internet connection refused, using local copy")
        print("Warning!! Local copy is from previous search and will ignore your inputed dates!!")
    else:
        #runs if the try succeeded
        while True:
            try:    
                with open('DocumentSearchResults.csv', 'w', newline='') as f:
                    f.write(secondr.text)
                break    
            except:
                print("File is in use or you dont have permission. Close the file and try again")
                input("press enter when ready to try again")

    finally:
        with open('DocumentSearchResults.csv', 'r', newline='') as f:
            count_events = len(f.readlines()) - 1 #counts the number of lines in the file to determin the num of events, subtracts 1 for the nonevent column names
            f.seek(0) #this returns the "read head to the beginning of the file, if this isnt done it starts reading from the end of the file returning no content"
            search_results_reader = [] #list to contain rows from the csv file
            for row in csv.reader(f, dialect='excel'):
                search_results_reader.append(row) # adding rows to the list

    search_results_cleaned = []
    for count, row in enumerate(search_results_reader):
        if count == 0:
            search_results_cleaned.append([*row[0:5], row[7],row[9], row[13],'ycoord', 'xcoord','fac_status', 'fac_type','fac_cleanup_status','documents'])
        if count > 1:
            if row[0].startswith('ERIC'):
               response = requests.get("https://ca.dep.state.fl.us/arcgis/rest/services/OpenData/CLEANUP_SP/MapServer/8/query?where=ERIC_ID%20%3D%20'"+row[0]+"'&outFields=*&outSR=4326&f=json")
            if row[0].isnumeric():
                response = requests.get("https://ca.dep.state.fl.us/arcgis/rest/services/OpenData/DWM_STCM/MapServer/1/query?where=%20FACILITY_ID%20%3D%20"+row[0]+"%20&outFields=*&outSR=4326&f=json")
            jsonobj = json.loads(response.text)
            xcoord = jsonobj['features'][0]['geometry']['x']
            ycoord = jsonobj['features'][0]['geometry']['y']
            search_results_cleaned.append([*row[0:5], row[7],row[9], row[13],ycoord, xcoord,])
    
    while True:
        try:
            with open('DocumentSearchResults_cleaned.csv', 'w', newline='') as f:
                writer = csv.writer(f, dialect='excel')
                writer.writerows(search_results_cleaned)
            break
        except:
                print("File is in use or you dont have permission. Close the file and try again")
                input("press enter when ready to try again")

   
                
    county_table_headers = ["County", "# of events"]
    county_table_body = rank_order_counties(search_results_reader)

    print(f'The number of events is : {count_events}')
    print('The rank order of the counties is :')
    print(tabulate(county_table_body, headers=county_table_headers))
    os.startfile('DocumentSearchResults_cleaned.csv')

if __name__ == "__main__":
    main()

