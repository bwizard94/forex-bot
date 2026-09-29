#property copyright "Forex Sentinel"
#property link      "https://github.com"
#property version   "2.22"
#property strict
#property description "Polls Forex Sentinel /api/mt4/bridge and mirrors EURUSD desk tickets. Magic 212100. Other magics stay hands-off."

input string HubUrl       = "http://127.0.0.1:8765";
input string BridgeSecret = "";
input int    Magic        = 212100;
input int    PollSeconds  = 5;
input string TradeSymbol  = "EURUSD";

int OnInit()
  {
   if(BridgeSecret == "")
     {
      Print("ForexSentinelBridge: set BridgeSecret (from hub Overview / .env MT4_BRIDGE_SECRET)");
      return(INIT_FAILED);
     }
   EventSetMillisecondTimer(MathMax(2000, PollSeconds * 1000));
   OnTimer();
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
  }

void OnTimer()
  {
   Print("ForexSentinelBridge poll ", HubUrl);
   string cmds = HttpGet(HubUrl + "/api/mt4/bridge?secret=" + UrlEncode(BridgeSecret));
   string results = "[]";
   if(StringFind(cmds, "\"ok\":true") >= 0 || StringFind(cmds, "\"ok\": true") >= 0)
      results = RunCommands(cmds);
   string body = "{\"secret\":\"" + JsonEscape(BridgeSecret) + "\",\"heartbeat\":" + HeartbeatJson() + ",\"results\":" + results + "}";
   HttpPost(HubUrl + "/api/mt4/bridge", body);
  }

string RunCommands(const string blob)
  {
   string out = "[";
   int added = 0;
   int searchFrom = 0;
   for(int n = 0; n < 8; n++)
     {
      int idPos = StringFind(blob, "\"id\":" , searchFrom);
      if(idPos < 0)
         idPos = StringFind(blob, "\"id\": ", searchFrom);
      if(idPos < 0)
         break;
      int cmdId = (int)StringToInteger(JsonNumberAfter(blob, idPos));
      string action = JsonStringField(blob, "action", idPos);
      string side = JsonStringField(blob, "side", idPos);
      double lots = StringToDouble(JsonNumberField(blob, "lots", idPos));
      double sl = StringToDouble(JsonNumberField(blob, "sl", idPos));
      double tp = StringToDouble(JsonNumberField(blob, "tp", idPos));
      int magic = (int)StringToInteger(JsonNumberField(blob, "magic", idPos));
      if(magic <= 0)
         magic = Magic;
      string comment = JsonStringField(blob, "comment", idPos);
      int ticket = (int)StringToInteger(JsonStringField(blob, "ticket", idPos));
      if(ticket <= 0)
         ticket = (int)StringToInteger(JsonNumberField(blob, "ticket", idPos));
      string piece = ExecuteCommand(cmdId, action, side, lots, sl, tp, magic, comment, ticket);
      if(added > 0)
         out += ",";
      out += piece;
      added++;
      searchFrom = idPos + 4;
     }
   out += "]";
   return(out);
  }

string ExecuteCommand(int cmdId, string action, string side, double lots, double sl, double tp, int magic, string comment, int ticket)
  {
   ResetLastError();
   bool ok = false;
   int newTicket = ticket;
   double fill = 0;
   string err = "";
   if(action == "open")
     {
      int type = (StringFind(side, "SELL") >= 0) ? OP_SELL : OP_BUY;
      double price = (type == OP_BUY) ? MarketInfo(TradeSymbol, MODE_ASK) : MarketInfo(TradeSymbol, MODE_BID);
      if(lots < 0.01)
         lots = 0.01;
      newTicket = OrderSend(TradeSymbol, type, lots, price, 30, sl, tp, comment, magic, 0, clrDodgerBlue);
      if(newTicket > 0)
        {
         ok = true;
         fill = price;
        }
      else
         err = "OrderSend " + IntegerToString(GetLastError());
     }
   else if(action == "close")
     {
      if(SelectOurs(ticket, magic))
        {
         double price = (OrderType() == OP_BUY) ? MarketInfo(TradeSymbol, MODE_BID) : MarketInfo(TradeSymbol, MODE_ASK);
         double vol = OrderLots();
         if(lots >= 0.01 && lots < vol - 0.005)
            vol = lots;
         ok = OrderClose(OrderTicket(), vol, price, 30, clrOrange);
         fill = price;
         newTicket = OrderTicket();
         if(!ok)
            err = "OrderClose " + IntegerToString(GetLastError());
        }
      else
         err = "ticket not found";
     }
   else if(action == "modify")
     {
      if(SelectOurs(ticket, magic))
        {
         ok = OrderModify(OrderTicket(), OrderOpenPrice(), sl, tp, 0, clrYellow);
         newTicket = OrderTicket();
         fill = OrderOpenPrice();
         if(!ok)
            err = "OrderModify " + IntegerToString(GetLastError());
        }
      else
         err = "ticket not found";
     }
   else
      err = "unknown action";
   string json = "{\"id\":" + IntegerToString(cmdId) + ",\"ok\":" + (ok ? "true" : "false") + ",\"ticket\":\"" + IntegerToString(newTicket) + "\"";
   if(fill > 0)
      json += ",\"fill\":" + DoubleToString(fill, 5);
   if(err != "")
      json += ",\"error\":\"" + JsonEscape(err) + "\"";
   json += "}";
   return(json);
  }

bool SelectOurs(int ticket, int magic)
  {
   if(ticket > 0 && OrderSelect(ticket, SELECT_BY_TICKET))
     {
      if(OrderMagicNumber() == magic || OrderMagicNumber() == Magic)
         return(true);
      return(false);
     }
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
         continue;
      if(OrderSymbol() != TradeSymbol)
         continue;
      if(OrderMagicNumber() != magic && OrderMagicNumber() != Magic)
         continue;
      return(true);
     }
   return(false);
  }

string HeartbeatJson()
  {
   string open = "[";
   int added = 0;
   for(int i = 0; i < OrdersTotal(); i++)
     {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
         continue;
      if(OrderSymbol() != TradeSymbol)
         continue;
      if(OrderMagicNumber() != Magic)
         continue;
      if(added > 0)
         open += ",";
      string typ = (OrderType() == OP_SELL) ? "SELL" : "BUY";
      open += "{\"ticket\":" + IntegerToString(OrderTicket()) +
              ",\"id\":\"" + IntegerToString(OrderTicket()) + "\"" +
              ",\"type\":\"" + typ + "\"" +
              ",\"volume\":" + DoubleToString(OrderLots(), 2) +
              ",\"openPrice\":" + DoubleToString(OrderOpenPrice(), 5) +
              ",\"stopLoss\":" + DoubleToString(OrderStopLoss(), 5) +
              ",\"takeProfit\":" + DoubleToString(OrderTakeProfit(), 5) +
              ",\"profit\":" + DoubleToString(OrderProfit(), 2) +
              ",\"magic\":" + IntegerToString(OrderMagicNumber()) +
              ",\"comment\":\"" + JsonEscape(OrderComment()) + "\"}";
      added++;
     }
   open += "]";
   return("{\"balance\":" + DoubleToString(AccountBalance(), 2) +
          ",\"equity\":" + DoubleToString(AccountEquity(), 2) +
          ",\"open\":" + open + "}");
  }

string HttpGet(const string url)
  {
   char data[];
   char result[];
   string headers = "Content-Type: application/json\r\n";
   string result_headers;
   int code = WebRequest("GET", url, headers, 4000, data, result, result_headers);
   if(code < 0)
     {
      Print("WebRequest GET failed ", code, " — allow ", HubUrl, " in Tools > Options > Expert Advisors");
      return("");
     }
   return(CharArrayToString(result));
  }

string HttpPost(const string url, const string body)
  {
   char data[];
   char result[];
   string headers = "Content-Type: application/json\r\n";
   string result_headers;
   int len = StringToCharArray(body, data, 0, WHOLE_ARRAY, CP_UTF8) - 1;
   if(len < 0)
      len = 0;
   ArrayResize(data, len);
   int code = WebRequest("POST", url, headers, 4000, data, result, result_headers);
   if(code < 0)
     {
      Print("WebRequest POST failed ", code);
      return("");
     }
   return(CharArrayToString(result));
  }

string JsonStringField(const string blob, const string key, const int from)
  {
   string needle = "\"" + key + "\":\"";
   int p = StringFind(blob, needle, from);
   if(p < 0)
     {
      needle = "\"" + key + "\": \"";
      p = StringFind(blob, needle, from);
     }
   if(p < 0)
      return("");
   int start = p + StringLen(needle);
   int end = StringFind(blob, "\"", start);
   if(end < 0)
      return("");
   return(StringSubstr(blob, start, end - start));
  }

string JsonNumberField(const string blob, const string key, const int from)
  {
   string needle = "\"" + key + "\":";
   int p = StringFind(blob, needle, from);
   if(p < 0)
     {
      needle = "\"" + key + "\": ";
      p = StringFind(blob, needle, from);
     }
   if(p < 0)
      return("0");
   return(JsonNumberAfter(blob, p));
  }

string JsonNumberAfter(const string blob, const int p)
  {
   int start = p;
   while(start < StringLen(blob) && StringGetChar(blob, start) != ':' )
      start++;
   start++;
   while(start < StringLen(blob) && (StringGetChar(blob, start) == ' ' || StringGetChar(blob, start) == '"'))
      start++;
   int end = start;
   while(end < StringLen(blob))
     {
      int ch = StringGetChar(blob, end);
      if((ch >= '0' && ch <= '9') || ch == '.' || ch == '-')
         end++;
      else
         break;
     }
   if(end <= start)
      return("0");
   return(StringSubstr(blob, start, end - start));
  }

string JsonEscape(const string s)
  {
   string o = s;
   StringReplace(o, "\\", "\\\\");
   StringReplace(o, "\"", "\\\"");
   return(o);
  }

string UrlEncode(const string s)
  {
   string o = s;
   StringReplace(o, "+", "%2B");
   StringReplace(o, "/", "%2F");
   StringReplace(o, "=", "%3D");
   return(o);
  }

void OnTick()
  {
  }
