PARAMETER_REGISTRY = {
    "Atmosphere": {
        "Temperature": {
            "T2": "Temperature at 2m",
            "TH2": "Potential Temperature at 2m",
            "TSK": "Skin Temperature",
        },
        "Wind": {
            "U10": "U Wind Component at 10m",
            "V10": "V Wind Component at 10m",
            "U": "Atmospheric U Wind",
            "V": "Atmospheric V Wind",
        },
        "Pressure": {
            "PSFC": "Surface Pressure",
            "MU": "Dry Air Mass",
            "MUB": "Base State Dry Air Mass",
        },
        "Humidity": {
            "Q2": "Specific Humidity at 2m",
            "CANWAT": "Canopy Water",
            "SNOWC": "Snow Cover Fraction",
        },
        "Clouds": {
            "CLDFRA": "Cloud Fraction",
            "CLOUD_FRAC": "Cloud Fraction",
            "COSZEN": "Cosine of Solar Zenith Angle",
            "EMISS": "Surface Emissivity",
        },
        "Radiation": {
            "SWDOWN": "Downward Shortwave Flux at Ground",
            "GLW": "Downward Longwave Flux at Ground",
            "SWUPT": "Upward Shortwave Flux at Top",
            "SWUPB": "Upward Shortwave Flux at Bottom",
            "SWDNT": "Downward Shortwave Flux at Top",
            "SWDNB": "Downward Shortwave Flux at Bottom",
            "LWUPT": "Upward Longwave Flux at Top",
            "LWUPB": "Upward Longwave Flux at Bottom",
            "LWDNT": "Downward Longwave Flux at Top",
            "LWDNB": "Downward Longwave Flux at Bottom",
            "OLR": "Outgoing Longwave Radiation",
            "ALBEDO": "Surface Albedo",
        },
    },
    "Precipitation": {
        "Rain": {
            "RAINC": "Convective Rain",
            "RAINNC": "Non-Convective Rain",
            "RAINSH": "Shallow Convective Rain",
            "SFROFF": "Surface Runoff",
            "UDROFF": "Underground Runoff",
        },
        "Snow": {
            "SNOW": "Snow Water Equivalent",
            "SNOWH": "Snow Height",
            "SNOWNC": "Snowfall",
            "SNOALB": "Snow Albedo",
            "SNOWC": "Snow Cover",
        },
        "Hail": {
            "HAILNC": "Hail Accumulation",
            "GRAUPELNC": "Graupel Accumulation",
        },
    },
    "Ocean": {
        "Sea Surface Temperature": {
            "SST": "Sea Surface Temperature",
            "SSTSK": "Sea Surface Skin Temperature",
            "SST_INPUT": "Input SST",
        },
        "Sea Ice": {
            "SEAICE": "Sea Ice Fraction",
            "XICEM": "Sea Ice Mask",
        },
        "Currents": {
            "U10": "Surface Current U Approximation",
            "V10": "Surface Current V Approximation",
        },
        "Waves": {
            "SWNORM": "Normalized Shortwave Flux",
            "SWDOWN": "Downward Shortwave Flux at Ground",
            "OLR": "Outgoing Longwave Radiation",
        },
        "Sea State": {
            "SST": "Sea Surface Temperature",
            "SEAICE": "Sea Ice Fraction",
            "U10": "U Wind Component at 10m",
            "V10": "V Wind Component at 10m",
            "PSFC": "Surface Pressure",
        },
    },
    "Land": {
        "Terrain": {
            "HGT": "Terrain Height",
            "VAR_SSO": "Terrain Variance",
            "MAPFAC_M": "Map Scale Factor",
            "MAPFAC_MX": "Map Scale Factor X",
            "MAPFAC_MY": "Map Scale Factor Y",
        },
        "Vegetation": {
            "VEGFRA": "Vegetation Fraction",
            "SHDMAX": "Maximum Vegetation Shade",
            "SHDMIN": "Minimum Vegetation Shade",
            "LAI": "Leaf Area Index",
            "IVGTYP": "Vegetation Type",
        },
        "Soil": {
            "TMN": "Soil Temperature Lower Boundary",
            "GRDFLX": "Ground Heat Flux",
            "ACGRDFLX": "Accumulated Ground Heat Flux",
            "ISLTYP": "Soil Type",
            "NOAHRES": "Noah LSM Residual",
        },
        "Land Use": {
            "LU_INDEX": "Land Use Category",
            "XLAND": "Land/Water Mask",
            "LANDMASK": "Land Mask",
            "LAKEMASK": "Lake Mask",
        },
    },
}
