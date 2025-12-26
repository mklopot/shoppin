<html>
<head>
<style>
p{
  width: 50%;
}

a:visited{
  color:blue;
}

a{
text-decoration: none
}

table, th, td {
  border: 1px dotted lightgray;
  border-collapse: collapse;
}
th, td {
  padding: 10px;
}
span.attribution{
  font-style: italic;
  font-size: 13px;
  color: gray;
}

.column {
  float: left;
  width: 50%;
}

.row:after {
  content: "";
  display: table;
  clear: both;
}

span.optional{
  color: gray;
}

a.x{
  opacity: 0.5;
  font-size: 0.8em;
  bottom: 0.3em;
  position: relative;
}

.greendot{
  opacity: 0.5;
  font-size: 0.8em;
}

.alreadyhave{
  text-align: center;
}

</style>
</head>
  <body>
    <h1><span style="color:green">Sort Shopping List Items Into Categories</span></h1>
    <form action="/categorize" method="POST">
    <label for="item">Item</label>
    <input type="text" id="item" name="item" placeholder="item name"><br>
    <label for="category">Category</label>
    <input list="categorylist" id="category" name="category" autocomplete="off" placeholder="category">
            <datalist id="categorylist">
            % for category in categories:
            <option value="{{category}}">
            % end
            </datalist>
    <br><br><input type="submit" value="Enter">
    </form>
    <br>
    <pre>
{{items}}
    </pre>
  </body>
</html>
