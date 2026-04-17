"""
Real Estate Days on Market Analyzer
A Dash web application for analyzing property days on market statistics.
"""

import base64
import io
from dash import Dash, html, dcc, callback, Output, Input, State, dash_table, ctx, ALL, no_update
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from scraper import RedfinScraper, filter_listings, calculate_dom_stats
from history_tracker import DOMHistoryTracker

# Initialize the app
app = Dash(__name__, suppress_callback_exceptions=True)
app.title = "Days on Market Analyzer"

# Initialize scraper and history tracker
scraper = RedfinScraper()
history_tracker = DOMHistoryTracker()

# App Layout
app.layout = html.Div([
    # Header
    html.Div([
        html.H1("Days on Market Analyzer", style={"margin": "0"}),
        html.P("Analyze real estate market trends by zip code or CSV upload",
               style={"margin": "5px 0 0 0", "color": "#666"})
    ], style={"textAlign": "center", "padding": "20px", "backgroundColor": "#f8f9fa",
              "borderBottom": "2px solid #dee2e6"}),

    # Main content container
    html.Div([
        # Left panel - Filters
        html.Div([
            html.H3("Data Source", style={"marginTop": "0"}),

            # Tabs for data source
            dcc.Tabs(id="data-source-tabs", value="upload", children=[
                dcc.Tab(label="Upload CSV", value="upload"),
                dcc.Tab(label="Fetch by Zip", value="fetch"),
            ], style={"marginBottom": "15px"}),

            # Upload section
            html.Div(id="upload-section", children=[
                html.P("Download CSV from Redfin, then upload here:",
                       style={"fontSize": "12px", "color": "#666", "marginBottom": "10px"}),
                dcc.Upload(
                    id="csv-upload",
                    children=html.Div([
                        "Drag & Drop or ",
                        html.A("Select CSV File", style={"color": "#007bff", "cursor": "pointer"})
                    ]),
                    style={
                        "width": "100%", "height": "80px", "lineHeight": "80px",
                        "borderWidth": "2px", "borderStyle": "dashed", "borderColor": "#ccc",
                        "borderRadius": "5px", "textAlign": "center", "marginBottom": "15px",
                        "backgroundColor": "#fafafa"
                    },
                    multiple=False
                ),
                html.Div([
                    html.P("How to get CSV from Redfin:", style={"fontWeight": "bold", "marginBottom": "5px"}),
                    html.Ol([
                        html.Li("Go to redfin.com"),
                        html.Li("Search your zip code"),
                        html.Li("Click 'Download All' button"),
                        html.Li("Upload the CSV file here"),
                    ], style={"fontSize": "12px", "paddingLeft": "20px", "color": "#666"})
                ], style={"backgroundColor": "#e9ecef", "padding": "10px", "borderRadius": "5px", "marginBottom": "15px"})
            ]),

            # Fetch section (hidden by default)
            html.Div(id="fetch-section", children=[
                html.Label("Zip Code", style={"fontWeight": "bold"}),
                dcc.Input(
                    id="zip-input",
                    type="text",
                    placeholder="Enter 5-digit zip code",
                    maxLength=5,
                    style={"width": "100%", "padding": "10px", "marginBottom": "15px",
                           "fontSize": "16px", "border": "1px solid #ccc", "borderRadius": "4px"}
                ),
                html.Button(
                    "Fetch Data",
                    id="fetch-button",
                    n_clicks=0,
                    style={
                        "width": "100%", "padding": "12px", "fontSize": "16px",
                        "backgroundColor": "#007bff", "color": "white", "border": "none",
                        "borderRadius": "5px", "cursor": "pointer", "fontWeight": "bold",
                        "marginBottom": "15px"
                    }
                ),
                html.P("Note: Redfin may block automated requests. CSV upload is more reliable.",
                       style={"fontSize": "11px", "color": "#999", "fontStyle": "italic"})
            ], style={"display": "none"}),

            html.Hr(style={"margin": "20px 0"}),

            html.H3("Filters", style={"marginTop": "0"}),

            # Price Range
            html.Label("Price Range ($)", style={"fontWeight": "bold"}),
            html.Div([
                dcc.Input(id="price-min", type="number", placeholder="Min",
                         style={"width": "45%", "padding": "8px", "marginRight": "5%"}),
                dcc.Input(id="price-max", type="number", placeholder="Max",
                         style={"width": "45%", "padding": "8px"})
            ], style={"marginBottom": "15px"}),

            # Square Footage
            html.Label("Square Footage", style={"fontWeight": "bold"}),
            html.Div([
                dcc.Input(id="sqft-min", type="number", placeholder="Min",
                         style={"width": "45%", "padding": "8px", "marginRight": "5%"}),
                dcc.Input(id="sqft-max", type="number", placeholder="Max",
                         style={"width": "45%", "padding": "8px"})
            ], style={"marginBottom": "15px"}),

            # Bedrooms
            html.Label("Bedrooms", style={"fontWeight": "bold"}),
            html.Div([
                dcc.Dropdown(
                    id="beds-min",
                    options=[{"label": f"{i}+", "value": i} for i in range(7)],
                    placeholder="Min",
                    style={"width": "45%", "display": "inline-block", "marginRight": "5%"}
                ),
                dcc.Dropdown(
                    id="beds-max",
                    options=[{"label": str(i), "value": i} for i in range(1, 11)],
                    placeholder="Max",
                    style={"width": "45%", "display": "inline-block"}
                )
            ], style={"marginBottom": "15px"}),

            # Bathrooms
            html.Label("Bathrooms", style={"fontWeight": "bold"}),
            html.Div([
                dcc.Dropdown(
                    id="baths-min",
                    options=[{"label": f"{i}+", "value": i} for i in range(7)],
                    placeholder="Min",
                    style={"width": "45%", "display": "inline-block", "marginRight": "5%"}
                ),
                dcc.Dropdown(
                    id="baths-max",
                    options=[{"label": str(i), "value": i} for i in range(1, 11)],
                    placeholder="Max",
                    style={"width": "45%", "display": "inline-block"}
                )
            ], style={"marginBottom": "15px"}),

            # Lot Size
            html.Label("Lot Size (sq ft)", style={"fontWeight": "bold"}),
            html.Div([
                dcc.Input(id="lot-min", type="number", placeholder="Min",
                         style={"width": "45%", "padding": "8px", "marginRight": "5%"}),
                dcc.Input(id="lot-max", type="number", placeholder="Max",
                         style={"width": "45%", "padding": "8px"})
            ], style={"marginBottom": "20px"}),

            # Apply Filters Button
            html.Button(
                "Apply Filters",
                id="apply-filters-button",
                n_clicks=0,
                style={
                    "width": "100%", "padding": "12px", "fontSize": "16px",
                    "backgroundColor": "#28a745", "color": "white", "border": "none",
                    "borderRadius": "5px", "cursor": "pointer", "fontWeight": "bold"
                }
            ),

            # Loading indicator
            dcc.Loading(id="loading", type="circle", children=html.Div(id="loading-output")),

            # Status message
            html.Div(id="status-message", style={"marginTop": "15px", "textAlign": "center"})

        ], style={
            "width": "300px", "padding": "20px", "backgroundColor": "#fff",
            "borderRadius": "8px", "boxShadow": "0 2px 10px rgba(0,0,0,0.1)",
            "marginRight": "20px", "flexShrink": "0", "maxHeight": "90vh", "overflowY": "auto"
        }),

        # Right panel - Results
        html.Div([
            # Stats Cards
            html.Div([
                html.Div([
                    html.H2(id="avg-dom", children="--", style={"margin": "0", "color": "#007bff"}),
                    html.P("Average DOM", style={"margin": "5px 0 0 0", "color": "#666"})
                ], style={
                    "flex": "1", "textAlign": "center", "padding": "20px",
                    "backgroundColor": "#fff", "borderRadius": "8px",
                    "boxShadow": "0 2px 10px rgba(0,0,0,0.1)", "margin": "0 10px"
                }),
                html.Div([
                    html.H2(id="median-dom", children="--", style={"margin": "0", "color": "#28a745"}),
                    html.P("Median DOM", style={"margin": "5px 0 0 0", "color": "#666"})
                ], style={
                    "flex": "1", "textAlign": "center", "padding": "20px",
                    "backgroundColor": "#fff", "borderRadius": "8px",
                    "boxShadow": "0 2px 10px rgba(0,0,0,0.1)", "margin": "0 10px"
                }),
                html.Div([
                    html.H2(id="total-props", children="--", style={"margin": "0", "color": "#6f42c1"}),
                    html.P("Properties", style={"margin": "5px 0 0 0", "color": "#666"})
                ], style={
                    "flex": "1", "textAlign": "center", "padding": "20px",
                    "backgroundColor": "#fff", "borderRadius": "8px",
                    "boxShadow": "0 2px 10px rgba(0,0,0,0.1)", "margin": "0 10px"
                }),
            ], style={"display": "flex", "marginBottom": "20px"}),

            # Histogram
            html.Div([
                dcc.Graph(
                    id="dom-histogram",
                    config={"displayModeBar": True, "displaylogo": False},
                    style={"height": "400px"}
                )
            ], style={
                "backgroundColor": "#fff", "borderRadius": "8px",
                "boxShadow": "0 2px 10px rgba(0,0,0,0.1)", "padding": "15px",
                "marginBottom": "20px"
            }),

            # Selected Range Info
            html.Div(id="selected-range-info", style={
                "padding": "10px", "backgroundColor": "#e9ecef",
                "borderRadius": "5px", "marginBottom": "15px", "display": "none"
            }),

            # DOM Trends Over Time Section
            html.Div([
                html.Div([
                    html.H4("DOM Trends Over Time", style={"marginTop": "0", "marginBottom": "0", "display": "inline-block"}),
                    html.Div([
                        html.Button(
                            "Save Snapshot",
                            id="save-snapshot-btn",
                            n_clicks=0,
                            style={
                                "padding": "6px 12px", "fontSize": "12px",
                                "backgroundColor": "#17a2b8", "color": "white",
                                "border": "none", "borderRadius": "4px",
                                "cursor": "pointer", "marginRight": "10px"
                            }
                        ),
                        html.Button(
                            "Clear History",
                            id="clear-history-btn",
                            n_clicks=0,
                            style={
                                "padding": "6px 12px", "fontSize": "12px",
                                "backgroundColor": "#dc3545", "color": "white",
                                "border": "none", "borderRadius": "4px",
                                "cursor": "pointer"
                            }
                        ),
                    ], style={"display": "inline-block", "float": "right"})
                ], style={"marginBottom": "15px", "overflow": "hidden"}),
                html.Div(id="snapshot-status", style={"marginBottom": "10px", "fontSize": "12px"}),
                dcc.Graph(
                    id="dom-trends-chart",
                    config={"displayModeBar": True, "displaylogo": False},
                    style={"height": "350px"}
                )
            ], style={
                "backgroundColor": "#fff", "borderRadius": "8px",
                "boxShadow": "0 2px 10px rgba(0,0,0,0.1)", "padding": "20px",
                "marginBottom": "20px"
            }),

            # History Management Section
            html.Div([
                html.Div([
                    html.H4("Manage History", style={"marginTop": "0", "marginBottom": "0", "display": "inline-block"}),
                    html.Button(
                        "Show",
                        id="toggle-history-btn",
                        n_clicks=0,
                        style={
                            "padding": "4px 12px", "fontSize": "12px",
                            "backgroundColor": "#6c757d", "color": "white",
                            "border": "none", "borderRadius": "4px",
                            "cursor": "pointer", "marginLeft": "15px",
                            "verticalAlign": "middle"
                        }
                    ),
                ], style={"marginBottom": "10px"}),
                html.Div(id="history-management-container", children=[
                    html.Div(id="history-table-container"),
                    # Edit modal (hidden by default)
                    html.Div(id="edit-modal", children=[
                        html.Div([
                            html.H4("Edit Entry", style={"marginTop": "0", "marginBottom": "15px"}),
                            dcc.Store(id="edit-timestamp-store"),
                            html.Div([
                                html.Label("Date", style={"fontWeight": "bold", "display": "block", "marginBottom": "4px"}),
                                dcc.Input(id="edit-date", type="text", placeholder="YYYY-MM-DD",
                                         style={"width": "100%", "padding": "8px", "marginBottom": "10px",
                                                "border": "1px solid #ccc", "borderRadius": "4px"}),
                            ]),
                            html.Div([
                                html.Div([
                                    html.Label("Avg DOM", style={"fontWeight": "bold", "display": "block", "marginBottom": "4px"}),
                                    dcc.Input(id="edit-avg-dom", type="number", step=0.1,
                                             style={"width": "100%", "padding": "8px",
                                                    "border": "1px solid #ccc", "borderRadius": "4px"}),
                                ], style={"flex": "1", "marginRight": "10px"}),
                                html.Div([
                                    html.Label("Properties", style={"fontWeight": "bold", "display": "block", "marginBottom": "4px"}),
                                    dcc.Input(id="edit-prop-count", type="number",
                                             style={"width": "100%", "padding": "8px",
                                                    "border": "1px solid #ccc", "borderRadius": "4px"}),
                                ], style={"flex": "1", "marginRight": "10px"}),
                                html.Div([
                                    html.Label("Avg Price", style={"fontWeight": "bold", "display": "block", "marginBottom": "4px"}),
                                    dcc.Input(id="edit-avg-price", type="number",
                                             style={"width": "100%", "padding": "8px",
                                                    "border": "1px solid #ccc", "borderRadius": "4px"}),
                                ], style={"flex": "1"}),
                            ], style={"display": "flex", "marginBottom": "15px"}),
                            html.Div([
                                html.Button("Save", id="edit-save-btn", n_clicks=0,
                                           style={"padding": "8px 20px", "backgroundColor": "#28a745",
                                                  "color": "white", "border": "none", "borderRadius": "4px",
                                                  "cursor": "pointer", "marginRight": "10px", "fontWeight": "bold"}),
                                html.Button("Cancel", id="edit-cancel-btn", n_clicks=0,
                                           style={"padding": "8px 20px", "backgroundColor": "#6c757d",
                                                  "color": "white", "border": "none", "borderRadius": "4px",
                                                  "cursor": "pointer"}),
                            ]),
                            html.Div(id="edit-status", style={"marginTop": "10px", "fontSize": "12px"}),
                        ], style={"padding": "20px", "backgroundColor": "#f8f9fa", "borderRadius": "8px",
                                  "border": "1px solid #dee2e6"})
                    ], style={"display": "none", "marginTop": "15px"}),
                ], style={"display": "none"}),
            ], style={
                "backgroundColor": "#fff", "borderRadius": "8px",
                "boxShadow": "0 2px 10px rgba(0,0,0,0.1)", "padding": "20px",
                "marginBottom": "20px"
            }),

            # Property Table
            html.Div([
                html.H4("Property Details", style={"marginTop": "0", "marginBottom": "15px"}),
                dash_table.DataTable(
                    id="property-table",
                    columns=[
                        {"name": "Address", "id": "ADDRESS"},
                        {"name": "Price", "id": "PRICE", "type": "numeric",
                         "format": {"specifier": "$,.0f"}},
                        {"name": "Beds", "id": "BEDS"},
                        {"name": "Baths", "id": "BATHS"},
                        {"name": "Sq Ft", "id": "SQUARE FEET", "type": "numeric",
                         "format": {"specifier": ",.0f"}},
                        {"name": "Lot Size", "id": "LOT SIZE", "type": "numeric",
                         "format": {"specifier": ",.0f"}},
                        {"name": "Days on Market", "id": "DAYS ON MARKET"}
                    ],
                    data=[],
                    page_size=10,
                    sort_action="native",
                    filter_action="native",
                    style_table={"overflowX": "auto"},
                    style_cell={
                        "textAlign": "left", "padding": "10px",
                        "whiteSpace": "normal", "height": "auto"
                    },
                    style_header={
                        "backgroundColor": "#f8f9fa", "fontWeight": "bold",
                        "borderBottom": "2px solid #dee2e6"
                    },
                    style_data_conditional=[
                        {"if": {"row_index": "odd"}, "backgroundColor": "#f8f9fa"}
                    ]
                )
            ], style={
                "backgroundColor": "#fff", "borderRadius": "8px",
                "boxShadow": "0 2px 10px rgba(0,0,0,0.1)", "padding": "20px"
            }),

            # Export Button
            html.Div([
                html.Button(
                    "Export to CSV",
                    id="export-button",
                    style={
                        "padding": "10px 20px", "fontSize": "14px",
                        "backgroundColor": "#6c757d", "color": "white",
                        "border": "none", "borderRadius": "5px", "cursor": "pointer"
                    }
                ),
                dcc.Download(id="download-csv")
            ], style={"marginTop": "15px", "textAlign": "right"})

        ], style={"flex": "1", "minWidth": "0"})

    ], style={
        "display": "flex", "padding": "20px", "maxWidth": "1400px",
        "margin": "0 auto", "alignItems": "flex-start"
    }),

    # Hidden stores for data
    dcc.Store(id="raw-data-store"),  # Unfiltered data
    dcc.Store(id="data-store"),       # Filtered data for display
    dcc.Store(id="history-trigger"),  # Trigger to refresh history chart
    dcc.Store(id="history-mgmt-trigger"),  # Trigger to refresh history management table

], style={"backgroundColor": "#f0f2f5", "minHeight": "100vh", "fontFamily": "Arial, sans-serif"})


# Toggle visibility of upload vs fetch sections
@callback(
    [Output("upload-section", "style"),
     Output("fetch-section", "style")],
    Input("data-source-tabs", "value")
)
def toggle_data_source(tab):
    if tab == "upload":
        return {"display": "block"}, {"display": "none"}
    else:
        return {"display": "none"}, {"display": "block"}


# Handle CSV upload
@callback(
    [Output("raw-data-store", "data", allow_duplicate=True),
     Output("status-message", "children", allow_duplicate=True)],
    Input("csv-upload", "contents"),
    State("csv-upload", "filename"),
    prevent_initial_call=True
)
def handle_csv_upload(contents, filename):
    if contents is None:
        return None, ""

    try:
        content_type, content_string = contents.split(',')
        decoded = base64.b64decode(content_string)
        df = pd.read_csv(io.StringIO(decoded.decode('utf-8')))

        # Normalize column names
        df.columns = df.columns.str.upper().str.strip()

        # Check for required columns
        if "DAYS ON MARKET" not in df.columns:
            # Try alternate column names
            for col in df.columns:
                if "DAYS" in col and "MARKET" in col:
                    df = df.rename(columns={col: "DAYS ON MARKET"})
                    break
                elif "DOM" == col:
                    df = df.rename(columns={col: "DAYS ON MARKET"})
                    break

        # Ensure required columns exist
        required = ["ADDRESS", "PRICE", "BEDS", "BATHS", "SQUARE FEET", "LOT SIZE", "DAYS ON MARKET"]
        for col in required:
            if col not in df.columns:
                df[col] = 0 if col != "ADDRESS" else "Unknown"

        # Convert numeric
        for col in ["PRICE", "BEDS", "BATHS", "SQUARE FEET", "LOT SIZE", "DAYS ON MARKET"]:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

        return (df.to_dict('records'),
                html.Span(f"Loaded {len(df)} properties from {filename}",
                         style={"color": "#28a745"}))

    except Exception as e:
        return None, html.Span(f"Error reading CSV: {str(e)}", style={"color": "#dc3545"})


# Handle fetch by zip
@callback(
    [Output("raw-data-store", "data", allow_duplicate=True),
     Output("status-message", "children", allow_duplicate=True),
     Output("loading-output", "children")],
    Input("fetch-button", "n_clicks"),
    State("zip-input", "value"),
    prevent_initial_call=True
)
def fetch_data(n_clicks, zip_code):
    if not zip_code or len(zip_code) != 5:
        return None, html.Span("Please enter a valid 5-digit zip code",
                              style={"color": "#dc3545"}), ""

    df = scraper.search_by_zip(zip_code)

    if df.empty:
        return None, html.Span("No data found. Try CSV upload instead.",
                              style={"color": "#dc3545"}), ""

    return (df.to_dict('records'),
            html.Span(f"Found {len(df)} properties", style={"color": "#28a745"}),
            "")


# Apply filters and update display
@callback(
    Output("data-store", "data"),
    [Input("apply-filters-button", "n_clicks"),
     Input("raw-data-store", "data")],
    [State("price-min", "value"),
     State("price-max", "value"),
     State("sqft-min", "value"),
     State("sqft-max", "value"),
     State("beds-min", "value"),
     State("beds-max", "value"),
     State("baths-min", "value"),
     State("baths-max", "value"),
     State("lot-min", "value"),
     State("lot-max", "value")]
)
def apply_filters(n_clicks, raw_data, price_min, price_max, sqft_min, sqft_max,
                  beds_min, beds_max, baths_min, baths_max, lot_min, lot_max):
    if not raw_data:
        return None

    df = pd.DataFrame(raw_data)

    filtered_df = filter_listings(
        df,
        min_price=price_min or 0,
        max_price=price_max or float('inf'),
        min_sqft=sqft_min or 0,
        max_sqft=sqft_max or float('inf'),
        min_beds=beds_min or 0,
        max_beds=beds_max or 100,
        min_baths=baths_min or 0,
        max_baths=baths_max or 100,
        min_lot=lot_min or 0,
        max_lot=lot_max or float('inf')
    )

    return filtered_df.to_dict('records')


# Update display when data changes
@callback(
    [Output("avg-dom", "children"),
     Output("median-dom", "children"),
     Output("total-props", "children"),
     Output("dom-histogram", "figure"),
     Output("property-table", "data")],
    Input("data-store", "data")
)
def update_display(data):
    if not data:
        empty_fig = go.Figure()
        empty_fig.update_layout(
            title="Days on Market Distribution",
            xaxis_title="Days on Market",
            yaxis_title="Number of Properties",
            template="plotly_white",
            annotations=[{
                "text": "Upload a CSV or fetch data to see results",
                "xref": "paper", "yref": "paper",
                "x": 0.5, "y": 0.5, "showarrow": False,
                "font": {"size": 16, "color": "#666"}
            }]
        )
        return "--", "--", "--", empty_fig, []

    df = pd.DataFrame(data)
    stats = calculate_dom_stats(df)

    # Filter out extreme outliers for better visualization (cap at 365 days)
    # but keep original data for stats
    dom_cap = 365
    df_viz = df.copy()
    df_viz["DAYS ON MARKET"] = df_viz["DAYS ON MARKET"].clip(upper=dom_cap)

    # Count how many are above cap
    outliers = len(df[df["DAYS ON MARKET"] > dom_cap])

    # Create histogram with fixed bins (0-365 days, 30-day intervals)
    fig = px.histogram(
        df_viz,
        x="DAYS ON MARKET",
        nbins=12,  # ~30 day bins
        title=f"Days on Market Distribution" + (f" ({outliers} properties > {dom_cap} days grouped in last bin)" if outliers > 0 else ""),
        labels={"DAYS ON MARKET": "Days on Market", "count": "Number of Properties"},
        color_discrete_sequence=["#007bff"]
    )

    fig.update_layout(
        template="plotly_white",
        xaxis_title="Days on Market",
        yaxis_title="Number of Properties",
        xaxis=dict(
            tickmode='linear',
            tick0=0,
            dtick=30,  # 30-day intervals
            range=[0, dom_cap + 10]
        ),
        bargap=0.1,
        hoverlabel=dict(bgcolor="white", font_size=14),
        clickmode="event+select"
    )

    fig.update_traces(
        hovertemplate="<b>Days on Market:</b> %{x}<br><b>Properties:</b> %{y}<extra></extra>",
        marker_line_color="white",
        marker_line_width=1
    )

    # Add average and median lines (capped for display)
    avg_display = min(stats["average"], dom_cap)
    median_display = min(stats["median"], dom_cap)
    fig.add_vline(x=avg_display, line_dash="dash", line_color="#dc3545",
                  annotation_text=f"Avg: {stats['average']}", annotation_position="top")
    fig.add_vline(x=median_display, line_dash="dash", line_color="#28a745",
                  annotation_text=f"Median: {stats['median']}", annotation_position="bottom")

    return (
        f"{stats['average']} days",
        f"{stats['median']} days",
        str(stats['count']),
        fig,
        data
    )


# Filter by histogram click
@callback(
    [Output("selected-range-info", "children"),
     Output("selected-range-info", "style"),
     Output("property-table", "data", allow_duplicate=True)],
    Input("dom-histogram", "clickData"),
    State("data-store", "data"),
    prevent_initial_call=True
)
def filter_by_histogram_click(click_data, data):
    if not click_data or not data:
        return "", {"display": "none"}, data or []

    df = pd.DataFrame(data)

    point = click_data["points"][0]
    bin_start = point.get("x", 0)

    dom_range = df["DAYS ON MARKET"].max() - df["DAYS ON MARKET"].min()
    bin_width = max(dom_range / 20, 1)
    bin_end = bin_start + bin_width

    filtered = df[
        (df["DAYS ON MARKET"] >= bin_start) &
        (df["DAYS ON MARKET"] < bin_end)
    ]

    info_text = f"Showing {len(filtered)} properties with {int(bin_start)}-{int(bin_end)} days on market. Click elsewhere to reset."

    return (
        info_text,
        {"padding": "10px", "backgroundColor": "#d4edda", "borderRadius": "5px",
         "marginBottom": "15px", "display": "block", "color": "#155724"},
        filtered.to_dict('records')
    )


# Export to CSV
@callback(
    Output("download-csv", "data"),
    Input("export-button", "n_clicks"),
    State("property-table", "data"),
    prevent_initial_call=True
)
def export_csv(n_clicks, data):
    if not data:
        return None
    df = pd.DataFrame(data)
    return dcc.send_data_frame(df.to_csv, "property_data.csv", index=False)


# Manual save snapshot
@callback(
    [Output("history-trigger", "data", allow_duplicate=True),
     Output("snapshot-status", "children", allow_duplicate=True)],
    Input("save-snapshot-btn", "n_clicks"),
    State("data-store", "data"),
    prevent_initial_call=True
)
def save_snapshot(n_clicks, data):
    if not data:
        return None, html.Span("No data to save. Upload a CSV first.",
                               style={"color": "#dc3545"})

    df = pd.DataFrame(data)
    snapshot = history_tracker.add_snapshot(df, label="Manual Save")

    if snapshot:
        return (
            {"timestamp": snapshot["timestamp"]},
            html.Span(f"Saved snapshot: Avg DOM {snapshot['avg_dom']} days, "
                     f"{snapshot['property_count']} properties",
                     style={"color": "#28a745"})
        )
    return None, html.Span("Failed to save snapshot", style={"color": "#dc3545"})


# Clear history
@callback(
    [Output("history-trigger", "data", allow_duplicate=True),
     Output("snapshot-status", "children", allow_duplicate=True)],
    Input("clear-history-btn", "n_clicks"),
    prevent_initial_call=True
)
def clear_history(n_clicks):
    history_tracker.clear_history()
    return {"cleared": True}, html.Span("History cleared", style={"color": "#6c757d"})


# Update DOM trends chart
@callback(
    Output("dom-trends-chart", "figure"),
    [Input("history-trigger", "data"),
     Input("data-store", "data")]  # Also trigger on new data load
)
def update_trends_chart(trigger, current_data):
    df = history_tracker.get_history_df()

    if df.empty:
        # Empty chart with message
        fig = go.Figure()
        fig.update_layout(
            title="DOM Trends Over Time",
            template="plotly_white",
            annotations=[{
                "text": "No historical data yet. Save snapshots to track trends over time.",
                "xref": "paper", "yref": "paper",
                "x": 0.5, "y": 0.5, "showarrow": False,
                "font": {"size": 14, "color": "#666"}
            }]
        )
        return fig

    # Create subplot with secondary y-axis for price
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # Average DOM line
    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=df["avg_dom"],
            mode="lines+markers",
            name="Avg DOM",
            line=dict(color="#007bff", width=2),
            marker=dict(size=8),
            hovertemplate="<b>Date:</b> %{x|%Y-%m-%d}<br>" +
                          "<b>Avg DOM:</b> %{y:.1f} days<extra></extra>"
        ),
        secondary_y=False
    )

    # Property count line
    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=df["property_count"],
            mode="lines+markers",
            name="Properties",
            line=dict(color="#28a745", width=2, dash="dot"),
            marker=dict(size=6),
            hovertemplate="<b>Date:</b> %{x|%Y-%m-%d}<br>" +
                          "<b>Properties:</b> %{y}<extra></extra>"
        ),
        secondary_y=False
    )

    # Average price line (secondary y-axis)
    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=df["avg_price"],
            mode="lines+markers",
            name="Avg Price",
            line=dict(color="#fd7e14", width=2),
            marker=dict(size=6),
            hovertemplate="<b>Date:</b> %{x|%Y-%m-%d}<br>" +
                          "<b>Avg Price:</b> $%{y:,.0f}<extra></extra>"
        ),
        secondary_y=True
    )

    fig.update_layout(
        title="DOM Trends Over Time",
        template="plotly_white",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        ),
        hovermode="x unified"
    )

    fig.update_xaxes(title_text="Date")
    fig.update_yaxes(title_text="Days on Market / Count", secondary_y=False)
    fig.update_yaxes(title_text="Average Price ($)", secondary_y=True)

    return fig


# Auto-save on CSV upload (modify existing callback to also save history)
@callback(
    Output("history-trigger", "data"),
    Input("raw-data-store", "data"),
    prevent_initial_call=True
)
def auto_save_on_upload(data):
    if not data:
        return None

    df = pd.DataFrame(data)
    if not df.empty:
        snapshot = history_tracker.add_snapshot(df, label="CSV Upload")
        if snapshot:
            return {"timestamp": snapshot["timestamp"]}
    return None


# Toggle history management panel visibility
@callback(
    [Output("history-management-container", "style"),
     Output("toggle-history-btn", "children")],
    Input("toggle-history-btn", "n_clicks"),
    prevent_initial_call=True
)
def toggle_history_panel(n_clicks):
    if n_clicks % 2 == 1:
        return {"display": "block"}, "Hide"
    return {"display": "none"}, "Show"


# Render history table
@callback(
    Output("history-table-container", "children"),
    [Input("history-mgmt-trigger", "data"),
     Input("history-management-container", "style")]
)
def render_history_table(trigger, style):
    history = history_tracker.get_history()
    if not history:
        return html.P("No history entries.", style={"color": "#666", "fontStyle": "italic"})

    rows = []
    for i, snap in enumerate(history):
        rows.append(
            html.Tr([
                html.Td(snap.get("date", ""), style={"padding": "8px"}),
                html.Td(snap.get("label", ""), style={"padding": "8px"}),
                html.Td(f"{snap.get('avg_dom', 0):.1f}", style={"padding": "8px"}),
                html.Td(str(snap.get("property_count", 0)), style={"padding": "8px"}),
                html.Td(f"${snap.get('avg_price', 0):,.0f}", style={"padding": "8px"}),
                html.Td([
                    html.Button("Edit", id={"type": "edit-btn", "index": i}, n_clicks=0,
                               style={"padding": "3px 10px", "fontSize": "11px",
                                      "backgroundColor": "#17a2b8", "color": "white",
                                      "border": "none", "borderRadius": "3px",
                                      "cursor": "pointer", "marginRight": "5px"}),
                    html.Button("Delete", id={"type": "delete-btn", "index": i}, n_clicks=0,
                               style={"padding": "3px 10px", "fontSize": "11px",
                                      "backgroundColor": "#dc3545", "color": "white",
                                      "border": "none", "borderRadius": "3px",
                                      "cursor": "pointer"}),
                ], style={"padding": "8px"})
            ], style={"borderBottom": "1px solid #dee2e6"})
        )

    table = html.Table([
        html.Thead(html.Tr([
            html.Th("Date", style={"padding": "8px", "fontWeight": "bold", "borderBottom": "2px solid #dee2e6"}),
            html.Th("Label", style={"padding": "8px", "fontWeight": "bold", "borderBottom": "2px solid #dee2e6"}),
            html.Th("Avg DOM", style={"padding": "8px", "fontWeight": "bold", "borderBottom": "2px solid #dee2e6"}),
            html.Th("Properties", style={"padding": "8px", "fontWeight": "bold", "borderBottom": "2px solid #dee2e6"}),
            html.Th("Avg Price", style={"padding": "8px", "fontWeight": "bold", "borderBottom": "2px solid #dee2e6"}),
            html.Th("Actions", style={"padding": "8px", "fontWeight": "bold", "borderBottom": "2px solid #dee2e6"}),
        ])),
        html.Tbody(rows)
    ], style={"width": "100%", "borderCollapse": "collapse", "fontSize": "13px"})

    return table


# Delete history entry
@callback(
    [Output("history-mgmt-trigger", "data", allow_duplicate=True),
     Output("history-trigger", "data", allow_duplicate=True)],
    Input({"type": "delete-btn", "index": ALL}, "n_clicks"),
    prevent_initial_call=True
)
def delete_history_entry(n_clicks_list):
    if not any(n_clicks_list):
        return no_update, no_update

    triggered = ctx.triggered_id
    if triggered and isinstance(triggered, dict):
        index = triggered["index"]
        history_tracker.delete_snapshot(index)
        return {"deleted": index}, {"deleted": index}
    return no_update, no_update


# Open edit modal with entry data
@callback(
    [Output("edit-modal", "style"),
     Output("edit-timestamp-store", "data"),
     Output("edit-date", "value"),
     Output("edit-avg-dom", "value"),
     Output("edit-prop-count", "value"),
     Output("edit-avg-price", "value")],
    Input({"type": "edit-btn", "index": ALL}, "n_clicks"),
    prevent_initial_call=True
)
def open_edit_modal(n_clicks_list):
    if not any(n_clicks_list):
        return {"display": "none"}, None, "", None, None, None

    triggered = ctx.triggered_id
    if triggered and isinstance(triggered, dict):
        index = triggered["index"]
        history = history_tracker.get_history()
        if 0 <= index < len(history):
            snap = history[index]
            return (
                {"display": "block", "marginTop": "15px"},
                snap.get("timestamp"),
                snap.get("date", ""),
                snap.get("avg_dom", 0),
                snap.get("property_count", 0),
                snap.get("avg_price", 0),
            )
    return {"display": "none"}, None, "", None, None, None


# Close edit modal on cancel
@callback(
    Output("edit-modal", "style", allow_duplicate=True),
    Input("edit-cancel-btn", "n_clicks"),
    prevent_initial_call=True
)
def close_edit_modal(n_clicks):
    return {"display": "none"}


# Save edit
@callback(
    [Output("edit-modal", "style", allow_duplicate=True),
     Output("history-mgmt-trigger", "data", allow_duplicate=True),
     Output("history-trigger", "data", allow_duplicate=True),
     Output("edit-status", "children")],
    Input("edit-save-btn", "n_clicks"),
    [State("edit-timestamp-store", "data"),
     State("edit-date", "value"),
     State("edit-avg-dom", "value"),
     State("edit-prop-count", "value"),
     State("edit-avg-price", "value")],
    prevent_initial_call=True
)
def save_edit(n_clicks, timestamp, date, avg_dom, prop_count, avg_price):
    if not timestamp:
        return no_update, no_update, no_update, html.Span("No entry selected", style={"color": "#dc3545"})

    history = history_tracker.get_history()
    for snap in history:
        if snap.get("timestamp") == timestamp:
            if date:
                snap["date"] = date
            if avg_dom is not None:
                snap["avg_dom"] = round(float(avg_dom), 1)
            if prop_count is not None:
                snap["property_count"] = int(prop_count)
            if avg_price is not None:
                snap["avg_price"] = round(float(avg_price), 0)
            history_tracker._save_history()
            return (
                {"display": "none"},
                {"edited": timestamp},
                {"edited": timestamp},
                ""
            )

    return no_update, no_update, no_update, html.Span("Entry not found", style={"color": "#dc3545"})


if __name__ == "__main__":
    print("Starting Days on Market Analyzer...")
    print("Open your browser to: http://127.0.0.1:8050")
    print("Press Ctrl+C to stop the server")
    app.run(debug=False, host="127.0.0.1", port=8050)
